import os
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
import time

import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

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

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "dummy_rapidapi_key")
RAPIDAPI_HOST = "live-golf-data.p.rapidapi.com"
LEADERBOARD_API_ENDPOINT = "https://live-golf-data.p.rapidapi.com/leaderboard"

SPORTSDATA_IO_API_KEY = os.getenv("SPORTSDATA_IO_API_KEY", "dummy_sportsdataio_key")

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

def parse_score_to_par(stp):
    if stp is None:
        return 0
    if isinstance(stp, int):
        return stp
    stp = str(stp).strip().upper()
    if stp in ("E", ""):
        return 0
    try:
        return int(stp)
    except ValueError:
        if stp.startswith("+"):
            try:
                return int(stp[1:])
            except Exception:
                return 0
        elif stp.startswith("-"):
            try:
                return int(stp)
            except Exception:
                return 0
    return 0

def format_score_to_par(value):
    if value == 0:
        return "E"
    elif value > 0:
        return f"+{value}"
    else:
        return str(value)

def apply_cut_penalty_to_leaderboard(data, course_par=72):
    """
    For each CUT player missing a round score, assign them:
    - strokes: (max strokes in that round among all active players) + 1
    - scoreToPar: (max scoreToPar in that round among all active players as int) + 1, formatted as string
    Keeps other fields matching actives.
    Handles BSON-like {"$numberInt": "N"} values.
    """
    if not data or "leaderboardRows" not in data:
        return data

    rows = data["leaderboardRows"]
    num_rounds = 4

    # Gather max strokes and max scoreToPar for each round, considering only active players
    round_strokes = {rnd: [] for rnd in range(1, num_rounds + 1)}
    round_scoretopar = {rnd: [] for rnd in range(1, num_rounds + 1)}
    for player in rows:
        status = str(player.get("status", "")).strip().lower()
        if status != "active":
            continue
        for round_info in player.get("rounds", []):
            round_id = round_info.get("roundId")
            round_num = None
            if isinstance(round_id, dict):
                round_num = int(round_id.get("$numberInt"))
            elif round_id is not None:
                round_num = int(round_id)
            if round_num is None or not (1 <= round_num <= num_rounds):
                continue
            # strokes
            strokes = round_info.get("strokes")
            strokes_val = None
            if isinstance(strokes, dict):
                strokes_val = strokes.get("$numberInt")
                if strokes_val is not None:
                    strokes_val = int(strokes_val)
            elif strokes is not None:
                try:
                    strokes_val = int(strokes)
                except Exception:
                    strokes_val = None
            if strokes_val is not None:
                round_strokes[round_num].append(strokes_val)
            # scoreToPar
            stp_val = round_info.get("scoreToPar")
            stp_int = parse_score_to_par(stp_val)
            round_scoretopar[round_num].append(stp_int)

    max_strokes = {rnd: (max(round_strokes[rnd]) if round_strokes[rnd] else 0) for rnd in range(1, num_rounds + 1)}
    max_scoretopar = {rnd: (max(round_scoretopar[rnd]) if round_scoretopar[rnd] else 0) for rnd in range(1, num_rounds + 1)}

    for player in rows:
        if str(player.get("status", "")).strip().lower() != "cut":
            continue
        existing_rounds = set()
        for r in player.get("rounds", []):
            round_id = r.get("roundId")
            round_num = None
            if isinstance(round_id, dict):
                round_num = int(round_id.get("$numberInt"))
            elif round_id is not None:
                round_num = int(round_id)
            if round_num is not None:
                existing_rounds.add(round_num)
        # Use courseId and courseName from player's first round (or set defaults)
        first_round = player.get("rounds", [{}])[0]
        course_id = first_round.get("courseId", "UNKNOWN")
        course_name = first_round.get("courseName", "UNKNOWN")
        for rnd in range(1, num_rounds + 1):
            if rnd not in existing_rounds and max_strokes[rnd] > 0:
                penalty_strokes = max_strokes[rnd] + 1
                penalty_scoretopar = max_scoretopar[rnd] + 1
                player.setdefault("rounds", []).append({
                    "courseId": course_id,
                    "courseName": course_name,
                    "roundId": {"$numberInt": str(rnd)},
                    "strokes": {"$numberInt": str(penalty_strokes)},
                    "scoreToPar": format_score_to_par(penalty_scoretopar),
                    "isPenalty": True
                })
        # Sort rounds
        player["rounds"] = sorted(
            player.get("rounds", []),
            key=lambda r: int(r.get("roundId", {}).get("$numberInt", r.get("roundId") or 0))
        )
        # Update totalStrokesFromCompletedRounds
        total_strokes = 0
        for r in player["rounds"]:
            strokes = r.get("strokes")
            strokes_val = None
            if isinstance(strokes, dict):
                strokes_val = strokes.get("$numberInt")
                if strokes_val is not None:
                    strokes_val = int(strokes_val)
            elif strokes is not None:
                try:
                    strokes_val = int(strokes)
                except Exception:
                    strokes_val = None
            if strokes_val is not None:
                total_strokes += strokes_val
        player["totalStrokesFromCompletedRounds"] = str(total_strokes)

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

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
