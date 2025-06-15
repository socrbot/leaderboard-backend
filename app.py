import os
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
import time
from datetime import datetime

# --- Firebase Admin SDK Imports ---
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# --- Firebase Initialization ---
FIREBASE_SERVICE_ACCOUNT_KEY_PATH = os.getenv("FIREBASE_SERVICE_ACCOUNT_KEY_PATH")
if FIREBASE_SERVICE_ACCOUNT_KEY_PATH:
    try:
        cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT_KEY_PATH)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        app.logger.info("Firebase Admin SDK initialized successfully.")
    except Exception as e:
        app.logger.error(f"Error initializing Firebase Admin SDK: {e}")
        db = None
else:
    app.logger.warning("FIREBASE_SERVICE_ACCOUNT_KEY_PATH not set, skipping Firebase init.")
    db = None

# RapidAPI credentials for leaderboard
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "dummy_rapidapi_key")
RAPIDAPI_HOST = "live-golf-data.p.rapidapi.com"
LEADERBOARD_API_ENDPOINT = "https://live-golf-data.p.rapidapi.com/leaderboard"

# SportsData.io credentials for odds
SPORTSDATA_IO_API_KEY = os.getenv("SPORTSDATA_IO_API_KEY", "dummy_sportsdataio_key")

# --- Cache variables (for both APIs) ---
CACHE = {}
CACHE_TTL_SECONDS = 5 * 60

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

def apply_cut_penalty_to_leaderboard(data):
    """
    For each CUT player missing a round score, assign them
    (max score in that round among all players) + 1 stroke,
    but only for rounds that are complete (all non-cut/non-withdrawn/non-dq players have a score).
    Handles BSON-like {"$numberInt": "N"} values.
    """
    if not data or "leaderboardRows" not in data:
        return data

    rows = data["leaderboardRows"]
    num_rounds = 4  # Adjust if needed

    # Step 1: Find which rounds are 'complete'
    complete_rounds = set()
    round_scores = {rnd: [] for rnd in range(1, num_rounds + 1)}
    for rnd in range(1, num_rounds + 1):
        all_scored = True
        for player in rows:
            status = player.get("status", "").strip().lower()
            if status in ["cut", "wd", "dq", "withdrawn", "disqualified"]:
                continue
            found_score = False
            for round_info in player.get("rounds", []):
                # Handle both dict and int roundId
                round_num = None
                round_id = round_info.get("roundId")
                if isinstance(round_id, dict):
                    round_num = int(round_id.get("$numberInt"))
                elif round_id is not None:
                    round_num = int(round_id)
                strokes = round_info.get("strokes")
                if isinstance(strokes, dict):
                    strokes = int(strokes.get("$numberInt"))
                elif strokes is not None:
                    strokes = int(strokes)
                if round_num == rnd and strokes is not None:
                    round_scores[rnd].append(strokes)
                    found_score = True
                    break
            if not found_score:
                all_scored = False
                break
        if all_scored and round_scores[rnd]:
            complete_rounds.add(rnd)

    # Step 2: Compute max scores per complete round
    max_scores = {}
    for rnd in complete_rounds:
        scores = round_scores[rnd]
        max_scores[rnd] = max(scores) if scores else None

    # Step 3: For each CUT player, fill in missing scores for complete rounds with (max + 1)
    for player in rows:
        if player.get("status", "").strip().lower() != "cut":
            continue
        existing_rounds = set()
        for r in player.get("rounds", []):
            round_id = r.get("roundId")
            if isinstance(round_id, dict):
                round_num = int(round_id.get("$numberInt"))
            elif round_id is not None:
                round_num = int(round_id)
            else:
                continue
            strokes = r.get("strokes")
            if isinstance(strokes, dict):
                strokes = int(strokes.get("$numberInt"))
            elif strokes is not None:
                strokes = int(strokes)
            else:
                continue
            existing_rounds.add(round_num)
        for rnd in complete_rounds:
            if rnd not in existing_rounds and max_scores[rnd] is not None:
                penalty_score = max_scores[rnd] + 1
                player.setdefault("rounds", []).append({
                    "roundId": {"$numberInt": str(rnd)},
                    "strokes": {"$numberInt": str(penalty_score)},
                    "isPenalty": True
                })
        player["rounds"] = sorted(
            player.get("rounds", []),
            key=lambda r: int(r.get("roundId", {}).get("$numberInt", r.get("roundId") or 0))
        )

    return data

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
    round_id = request.args.get('roundId', None)
    rapidapi_url = f"{LEADERBOARD_API_ENDPOINT}?orgId={org_id}&tournId={tourn_id}&year={year}"
    if round_id:
        rapidapi_url += f"&roundId={round_id}"
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

# (Other endpoints related to odds, teams, etc. would go here; unchanged from your previous code.)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
