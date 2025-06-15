import os
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
import time
import json
from datetime import datetime

# --- Firebase Admin SDK Imports ---
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# --- CORS Configuration ---
CORS(app, resources={r"/api/*": {"origins": "*"}})

# --- Firebase Initialization ---
FIREBASE_SERVICE_ACCOUNT_KEY_PATH = os.getenv("FIREBASE_SERVICE_ACCOUNT_KEY_PATH")

if not FIREBASE_SERVICE_ACCOUNT_KEY_PATH:
    app.logger.critical("FIREBASE_SERVICE_ACCOUNT_KEY_PATH environment variable not set. Exiting.")
    raise EnvironmentError("FIREBASE_SERVICE_ACCOUNT_KEY_PATH environment variable not set.")

try:
    cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT_KEY_PATH)
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    app.logger.info("Firebase Admin SDK initialized successfully.")
except Exception as e:
    app.logger.error(f"Error initializing Firebase Admin SDK: {e}")
    db = None

# RapidAPI credentials for leaderboard
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
RAPIDAPI_HOST = "live-golf-data.p.rapidapi.com"
LEADERBOARD_API_ENDPOINT = "https://live-golf-data.p.rapidapi.com/leaderboard"

# SportsData.io credentials for odds
SPORTSDATA_IO_API_KEY = os.getenv("SPORTSDATA_IO_API_KEY")

if not RAPIDAPI_KEY:
    app.logger.warning("RAPIDAPI_KEY environment variable not set. Using dummy key.")
    RAPIDAPI_KEY = "dummy_rapidapi_key"
if not SPORTSDATA_IO_API_KEY:
    app.logger.warning("SPORTSDATA_IO_API_KEY environment variable not set. Using dummy key.")
    SPORTSDATA_IO_API_KEY = "dummy_sportsdataio_key"

# --- Cache variables (for both APIs) ---
CACHE = {}
CACHE_TTL_SECONDS = 5 * 60

# Helper function to calculate average odds (unchanged)
def calculate_average_odds(player_odds_data):
    player_odds_map = {}
    for player_entry in player_odds_data:
        player_name = player_entry.get("Name")
        odds_to_win = player_entry.get("OddsToWin")
        if player_name and odds_to_win is not None:
            try:
                numeric_odds = float(odds_to_win)
                if player_name in player_odds_map:
                    player_odds_map[player_name].append(numeric_odds)
                else:
                    player_odds_map[player_name] = [numeric_odds]
            except ValueError:
                app.logger.warning(f"Could not parse odds for {player_name}: {odds_to_win}")
                continue
    averaged_odds = []
    for player_name, odds_array in player_odds_map.items():
        valid_odds = [odds for odds in odds_array if odds > 0]
        if valid_odds:
            average = sum(valid_odds) / len(valid_odds)
            averaged_odds.append({"name": player_name, "averageOdds": average})
        else:
            averaged_odds.append({"name": player_name, "averageOdds": None})
    averaged_odds.sort(key=lambda x: x['averageOdds'] if x['averageOdds'] is not None else float('inf'))
    return averaged_odds

# --- CUT Penalty Transformation ---
def apply_cut_penalty_to_leaderboard(data):
    """
    For each CUT player missing a round score, assign them
    (max score in that round among all players) + 1 stroke.
    Assumes 'leaderboardRows' is a list of players, each with 'status' and 'rounds'.
    """
    if not data or "leaderboardRows" not in data:
        return data

    rows = data["leaderboardRows"]
    num_rounds = 4  # Adjust if your tournament uses a different number

    # Step 1: Gather all scores for each round
    round_scores = {rnd: [] for rnd in range(1, num_rounds + 1)}
    for player in rows:
        for round_info in player.get("rounds", []):
            try:
                round_num = int(round_info.get("roundId") or round_info.get("roundId", {}).get("$numberInt"))
                strokes = round_info.get("strokes")
                # Unwrap MongoDB style integer if present
                if isinstance(strokes, dict):
                    strokes = int(strokes.get("$numberInt"))
                elif strokes is not None:
                    strokes = int(strokes)
                else:
                    strokes = None
                if strokes is not None:
                    round_scores[round_num].append(strokes)
            except Exception:
                continue

    # Step 2: Compute max scores per round
    max_scores = {}
    for rnd in range(1, num_rounds + 1):
        scores = round_scores[rnd]
        max_scores[rnd] = max(scores) if scores else None

    # Step 3: For each CUT player, fill in missing round scores with (max + 1)
    for player in rows:
        if player.get("status", "").upper() != "CUT":
            continue
        # Map of round numbers that already exist for this player
        existing_rounds = {
            int(r.get("roundId") or r.get("roundId", {}).get("$numberInt")): r
            for r in player.get("rounds", [])
            if r.get("strokes") is not None
        }
        for rnd in range(1, num_rounds + 1):
            if rnd not in existing_rounds and max_scores[rnd] is not None:
                penalty_score = max_scores[rnd] + 1
                # Append new round with penalty
                player.setdefault("rounds", []).append({
                    "roundId": rnd,
                    "strokes": penalty_score,
                    "isPenalty": True  # Optional: mark as penalty for frontend
                })
        # Sort rounds for display order
        player["rounds"] = sorted(
            player.get("rounds", []),
            key=lambda r: int(r.get("roundId") or r.get("roundId", {}).get("$numberInt", 0))
        )

    return data

# --- Leaderboard API Route (with CUT penalty) ---
@app.route('/api/leaderboard', methods=['GET'])
def get_leaderboard():
    cache_key_params = request.args.to_dict()
    cache_key = ('leaderboard', tuple(sorted(cache_key_params.items())))
    if cache_key in CACHE:
        cached_data, timestamp = CACHE[cache_key]
        if (time.time() - timestamp) < CACHE_TTL_SECONDS:
            app.logger.info("Returning cached data for leaderboard.")
            return jsonify(cached_data)
    app.logger.info("Fetching fresh data from RapidAPI.")
    org_id = request.args.get('orgId', '1')
    tourn_id = request.args.get('tournId', '033')
    year = request.args.get('year', '2025')
    rapidapi_url = f"{LEADERBOARD_API_ENDPOINT}?orgId={org_id}&tournId={tourn_id}&year={year}"
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": RAPIDAPI_HOST
    }
    try:
        response = requests.get(rapidapi_url, headers=headers)
        response.raise_for_status()
        data = response.json()
        # --- Apply CUT penalty logic here ---
        data = apply_cut_penalty_to_leaderboard(data)
        CACHE[cache_key] = (data, time.time())
        return jsonify(data)
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error fetching leaderboard from RapidAPI: {e}")
        details = str(e)
        if e.response is not None:
            details += f" | Status: {e.response.status_code} | Content: {e.response.text}"
        return jsonify({"error": "Failed to fetch leaderboard data", "details": details}), 500
    except ValueError:
        app.logger.error("Failed to parse JSON response from RapidAPI (leaderboard)")
        return jsonify({"error": "Invalid JSON response from external API"}), 500

# --- Player Odds API Route (unchanged) ---
@app.route('/api/player_odds', methods=['GET'])
def get_player_odds():
    odds_id = request.args.get('oddsId')
    if not odds_id:
        app.logger.error("Missing 'oddsId' parameter for player odds API.")
        return jsonify({"error": "Missing oddsId parameter"}), 400

    # NEW: Check if the draft has started and locked odds are available in Firestore
    try:
        tournaments_ref = db.collection('tournaments').where('oddsId', '==', odds_id).limit(1).get()
        tournament_doc = None
        for doc in tournaments_ref:
            tournament_doc = doc
            break

        if tournament_doc and tournament_doc.exists:
            tournament_data = tournament_doc.to_dict()
            if tournament_data.get('IsDraftStarted') and tournament_data.get('DraftLockedOdds'):
                app.logger.info(f"Returning LOCKED draft odds for tournament with oddsId: {odds_id}")
                return jsonify(tournament_data['DraftLockedOdds'])

    except Exception as e:
        app.logger.error(f"Error checking Firestore for locked odds for oddsId {odds_id}: {e}")

    # Original logic: Fetch fresh player odds from SportsData.io if not locked
    cache_key_params = request.args.to_dict()
    cache_key = ('player_odds', tuple(sorted(cache_key_params.items())))

    if cache_key in CACHE:
        cached_data, timestamp = CACHE[cache_key]
        if (time.time() - timestamp) < CACHE_TTL_SECONDS:
            app.logger.info("Returning cached data for player odds (live).")
            return jsonify(cached_data)

    app.logger.info("Fetching fresh player odds from SportsData.io.")

    dynamic_odds_api_endpoint = f"https://api.sportsdata.io/v3/golf/odds/json/TournamentOdds/{odds_id}"
    app.logger.info(f"Fetching player odds from SportsData.io URL: {dynamic_odds_api_endpoint}")

    headers = {
        "Ocp-Apim-Subscription-Key": SPORTSDATA_IO_API_KEY
    }
    try:
        response = requests.get(dynamic_odds_api_endpoint, headers=headers)
        response.raise_for_status()
        data = response.json()
        if not data or not data.get("PlayerTournamentOdds"):
            app.logger.warning("SportsData.io response missing PlayerTournamentOdds for oddsId: %s", odds_id)
            return jsonify({"error": "Unexpected API response structure for player odds."}), 500

        raw_player_odds = data["PlayerTournamentOdds"]
        averaged_odds_list = calculate_average_odds(raw_player_odds)
        CACHE[cache_key] = (averaged_odds_list, time.time())
        return jsonify(averaged_odds_list)
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error fetching player odds from SportsData.io for oddsId {odds_id}: {e}")
        details = str(e)
        if e.response is not None:
            details += f" | Status: {e.response.status_code} | Content: {e.response.text}"
        return jsonify({"error": "Failed to fetch player odds data", "details": details}), 500
    except ValueError:
        app.logger.error("Failed to parse JSON response from SportsData.io (player odds) for oddsId %s", odds_id)
        return jsonify({"error": "Invalid JSON response from external API"}), 500

# --- Tournament Management API Routes (unchanged except for standard logic) ---

@app.route('/api/tournaments', methods=['POST'])
def create_tournament():
    if not db:
        app.logger.error("Firestore DB not initialized.")
        return jsonify({"error": "Firestore not initialized"}), 500
    try:
        data = request.json
        if not data or 'name' not in data:
            return jsonify({"error": "Missing 'name' for new tournament"}), 400

        tournament_name = data['name'].strip()
        org_id = data.get('orgId', '').strip()
        tourn_id = data.get('tournId', '').strip()
        year = data.get('year', '').strip()
        odds_id = data.get('oddsId', '').strip()

        if not tournament_name or not org_id or not tourn_id or not year or not odds_id:
            return jsonify({"error": "Missing tournament name, Org ID, Tourn ID, Year, or Odds ID in request data"}), 400

        new_tournament_data = {
            "name": tournament_name,
            "orgId": org_id,
            "tournId": tourn_id,
            "year": year,
            "oddsId": odds_id,
            "teams": [],
            "IsDraftStarted": False,
            "DraftLockedOdds": [],
            "createdAt": firestore.SERVER_TIMESTAMP
        }
        doc_ref = db.collection('tournaments').add(new_tournament_data)
        return jsonify({"message": "Tournament created successfully", "id": doc_ref[1].id, "name": tournament_name}), 201
    except Exception as e:
        app.logger.error(f"Error creating tournament: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/tournaments', methods=['GET'])
def get_tournaments():
    if not db:
        app.logger.error("Firestore DB not initialized.")
        return jsonify({"error": "Firestore not initialized"}), 500
    try:
        tournaments_ref = db.collection('tournaments').order_by('createdAt').get()
        tournaments_list = []
        for doc in tournaments_ref:
            tournament_data = doc.to_dict()
            tournaments_list.append({
                "id": doc.id,
                "name": tournament_data.get("name", "Unnamed Tournament"),
            })
        return jsonify(tournaments_list), 200
    except Exception as e:
        app.logger.error(f"Error fetching tournaments: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/tournaments/<tournament_id>', methods=['GET'])
def get_single_tournament(tournament_id):
    if not db:
        app.logger.error("Firestore DB not initialized.")
        return jsonify({"error": "Firestore not initialized"}), 500

    try:
        doc_ref = db.collection('tournaments').document(tournament_id)
        doc = doc_ref.get()

        if not doc.exists:
            return jsonify({"error": "Tournament not found"}), 404

        tournament_data = doc.to_dict()
        odds_id = tournament_data.get("oddsId")

        # Initialize default values for API-derived status
        is_in_progress_from_api = False
        is_over_from_api = False
        tournament_par = tournament_data.get("par", 71)

        # Fetch IsInProgress and IsOver from SportsData.io Tournament Odds API
        if odds_id:
            sportsdata_io_tournament_odds_endpoint = f"https://api.sportsdata.io/v3/golf/odds/json/TournamentOdds/{odds_id}"
            headers = {
                "Ocp-Apim-Subscription-Key": SPORTSDATA_IO_API_KEY
            }
            try:
                cache_key = ('sportsdata_tournament_details', odds_id)
                if cache_key in CACHE:
                    cached_odds_data, timestamp = CACHE[cache_key]
                    if (time.time() - timestamp) < CACHE_TTL_SECONDS:
                        app.logger.info(f"Returning cached SportsData.io tournament details for oddsId {odds_id}.")
                        odds_api_data = cached_odds_data
                    else:
                        del CACHE[cache_key]
                        app.logger.warning(f"Cached SportsData.io data for {odds_id} expired, refetching.")
                        response = requests.get(sportsdata_io_tournament_odds_endpoint, headers=headers)
                        response.raise_for_status()
                        odds_api_data = response.json()
                        CACHE[cache_key] = (odds_api_data, time.time())
                else:
                    app.logger.info(f"Fetching live SportsData.io tournament details for oddsId {odds_id}.")
                    response = requests.get(sportsdata_io_tournament_odds_endpoint, headers=headers)
                    response.raise_for_status()
                    odds_api_data = response.json()
                    CACHE[cache_key] = (odds_api_data, time.time())

                if odds_api_data and odds_api_data.get("Tournament"):
                    is_in_progress_from_api = odds_api_data["Tournament"].get("IsInProgress", False)
                    is_over_from_api = odds_api_data["Tournament"].get("IsOver", False)
                    tournament_par = odds_api_data["Tournament"].get("Par", tournament_par)
                else:
                    app.logger.warning(f"SportsData.io response missing 'Tournament' info for oddsId: {odds_id}")

            except requests.exceptions.RequestException as e:
                app.logger.error(f"Error fetching live tournament status from SportsData.io for oddsId {odds_id}: {e}")
            except ValueError:
                app.logger.error(f"Failed to parse JSON response from SportsData.io (tournament status) for oddsId {odds_id}")

        show_leaderboard_on_frontend = is_in_progress_from_api or is_over_from_api

        response_data = {
            "id": doc.id,
            **tournament_data,
            "IsInProgress": show_leaderboard_on_frontend,
            "IsOver": is_over_from_api,
            "par": tournament_par,
            "IsDraftStarted": tournament_data.get('IsDraftStarted', False)
        }
        return jsonify(response_data), 200

    except Exception as e:
        app.logger.error(f"Error fetching single tournament {tournament_id}: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/tournaments/<tournament_id>/teams', methods=['PUT'])
def update_tournament_teams(tournament_id):
    if not db:
        app.logger.error("Firestore DB not initialized.")
        return jsonify({"error": "Firestore not initialized"}), 500
    try:
        data = request.json
        if not data or 'teams' not in data or not isinstance(data['teams'], list):
            return jsonify({"error": "Invalid data format. Expected JSON with a 'teams' array."}), 400
        doc_ref = db.collection('tournaments').document(tournament_id)
        doc = doc_ref.get()
        if not doc.exists:
            return jsonify({"error": "Tournament not found"}), 404
        doc_ref.update({"teams": data['teams']})
        return jsonify({"message": f"Teams for tournament {tournament_id} updated successfully"}), 200
    except Exception as e:
        app.logger.error(f"Error updating teams for tournament {tournament_id}: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/tournaments/<tournament_id>/start_draft', methods=['POST'])
def start_draft(tournament_id):
    if not db:
        app.logger.error("Firestore DB not initialized.")
        return jsonify({"error": "Firestore not initialized"}), 500

    try:
        doc_ref = db.collection('tournaments').document(tournament_id)
        doc = doc_ref.get()

        if not doc.exists:
            return jsonify({"error": "Tournament not found"}), 404

        tournament_data = doc.to_dict()
        if tournament_data.get('IsDraftStarted'):
            return jsonify({"message": "Draft has already started for this tournament."}), 409

        odds_id = tournament_data.get("oddsId")
        if not odds_id:
            return jsonify({"error": "Tournament does not have an Odds ID configured."}), 400

        app.logger.info(f"Fetching live player odds to lock in for tournament {tournament_id} (oddsId: {odds_id}).")
        dynamic_odds_api_endpoint = f"https://api.sportsdata.io/v3/golf/odds/json/TournamentOdds/{odds_id}"
        headers = {
            "Ocp-Apim-Subscription-Key": SPORTSDATA_IO_API_KEY
        }
        try:
            response = requests.get(dynamic_odds_api_endpoint, headers=headers)
            response.raise_for_status()
            data = response.json()
            if not data or not data.get("PlayerTournamentOdds"):
                app.logger.warning("SportsData.io response missing PlayerTournamentOdds when trying to lock odds for oddsId: %s", odds_id)
                return jsonify({"error": "Could not retrieve live odds to lock in. API response missing player data."}), 500

            raw_player_odds = data["PlayerTournamentOdds"]
            averaged_odds_list = calculate_average_odds(raw_player_odds)

            doc_ref.update({
                "IsDraftStarted": True,
                "DraftLockedOdds": averaged_odds_list,
                "DraftStartedAt": firestore.SERVER_TIMESTAMP
            })

            return jsonify({"message": f"Draft started and odds locked for tournament {tournament_id}."}), 200

        except requests.exceptions.RequestException as e:
            a