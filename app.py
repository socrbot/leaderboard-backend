import os
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS # Ensure this is imported
from dotenv import load_dotenv
import time
import json

# --- Firebase Admin SDK Imports ---
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# --- CORS Configuration ---
# Use the most permissive setting for development, then narrow it down for production.
# This should be your ONLY CORS(app) line
CORS(app, resources={r"/api/*": {"origins": "*"}}) # Allows ALL origins for /api routes

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
    db = None # Set db to None if initialization fails

# RapidAPI credentials for leaderboard
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
RAPIDAPI_HOST = "live-golf-data.p.rapidapi.com"
LEADERBOARD_API_ENDPOINT = "https://live-golf-data.p.rapidapi.com/leaderboard"

# SportsData.io credentials for odds
SPORTSDATA_IO_API_KEY = os.getenv("SPORTSDATA_IO_API_KEY")
SPORTSDATA_IO_TOURNAMENT_ID = os.getenv("SPORTSDATA_IO_TOURNAMENT_ID", "630")
SPORTSDATA_IO_ODDS_API_ENDPOINT = f"https://api.sportsdata.io/v3/golf/odds/json/TournamentOdds/{SPORTSDATA_IO_TOURNAMENT_ID}"

if not RAPIDAPI_KEY:
    app.logger.warning("RAPIDAPI_KEY environment variable not set. Using dummy key.")
    RAPIDAPI_KEY = "dummy_rapidapi_key"
if not SPORTSDATA_IO_API_KEY:
    app.logger.warning("SPORTSDATA_IO_API_KEY environment variable not set. Using dummy key.")
    SPORTSDATA_IO_API_KEY = "dummy_sportsdataio_key"


# --- Cache variables (for both APIs) ---
CACHE = {}
CACHE_TTL_SECONDS = 5 * 60

# Helper function to calculate average odds
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

# --- Leaderboard API Route ---
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

# --- Player Odds API Route ---
@app.route('/api/player_odds', methods=['GET'])
def get_player_odds():
    cache_key = ('player_odds',)
    if cache_key in CACHE:
        cached_data, timestamp = CACHE[cache_key]
        if (time.time() - timestamp) < CACHE_TTL_SECONDS:
            app.logger.info("Returning cached data for player odds.")
            return jsonify(cached_data)
    app.logger.info("Fetching fresh player odds from SportsData.io.")
    headers = {
        "Ocp-Apim-Subscription-Key": SPORTSDATA_IO_API_KEY
    }
    try:
        response = requests.get(SPORTSDATA_IO_ODDS_API_ENDPOINT, headers=headers)
        response.raise_for_status()
        data = response.json()
        if not data or not data.get("PlayerTournamentOdds"):
            app.logger.warning("SportsData.io response missing PlayerTournamentOdds.")
            return jsonify({"error": "Unexpected API response structure for player odds."}), 500
        raw_player_odds = data["PlayerTournamentOdds"]
        averaged_odds_list = calculate_average_odds(raw_player_odds)
        CACHE[cache_key] = (averaged_odds_list, time.time())
        return jsonify(averaged_odds_list)
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error fetching player odds from SportsData.io: {e}")
        details = str(e)
        if e.response is not None:
            details += f" | Status: {e.response.status_code} | Content: {e.response.text}"
        return jsonify({"error": "Failed to fetch player odds data", "details": details}), 500
    except ValueError:
        app.logger.error("Failed to parse JSON response from SportsData.io (player odds)")
        return jsonify({"error": "Invalid JSON response from external API"}), 500

# --- Temporary Test Routes for Firebase DB (REMOVE THESE AFTER SUCCESSFUL TESTING) ---
@app.route('/api/test_firestore_write', methods=['POST'])
def test_firestore_write():
    if not db:
        app.logger.error("Firestore DB object is None, Firebase Admin SDK might not be initialized.")
        return jsonify({"error": "Firestore not initialized"}), 500
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Request body must be JSON"}), 400
        doc_ref = db.collection('test_collection').add(data)
        return jsonify({"message": "Document added", "id": doc_ref[1].id}), 200
    except Exception as e:
        app.logger.error(f"Firestore write error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/test_firestore_read', methods=['GET'])
def test_firestore_read():
    if not db:
        app.logger.error("Firestore DB object is None, Firebase Admin SDK might not be initialized.")
        return jsonify({"error": "Firestore not initialized"}), 500
    try:
        docs = db.collection('test_collection').limit(1).get()
        results = []
        for doc in docs:
            results.append({"id": doc.id, **doc.to_dict()})
        return jsonify(results), 200
    except Exception as e:
        app.logger.error(f"Firestore read error: {e}")
        return jsonify({"error": str(e)}), 500
# --- END Temporary Test Routes ---

# --- NEW: Tournament Management API Routes ---

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
        # --- NEW: Get par from the request JSON, with a default ---
        par = data.get('par', 71) # Default to 71 if not provided

        if not tournament_name or not org_id or not tourn_id or not year:
            return jsonify({"error": "Missing tournament name, Org ID, Tourn ID, or Year in request data"}), 400

        new_tournament_data = {
            "name": tournament_name,
            "orgId": org_id,
            "tournId": tourn_id,
            "year": year,
            "par": par, # --- NEW: Store the par value ---
            "teams": [],
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
        # The 'par' will be automatically included in tournament_data if stored
        return jsonify({"id": doc.id, **tournament_data}), 200
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

# --- Flask App Run ---
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)