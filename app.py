import os
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_compress import Compress
from flask_caching import Cache
from dotenv import load_dotenv
import time
import json
from datetime import datetime
import hashlib
import functools

# --- Firebase Admin SDK Imports ---
import firebase_admin
from firebase_admin import credentials, firestore

# Load environment variables from .env file
# load_dotenv()

app = Flask(__name__)

# --- Compression Configuration ---
Compress(app)

# --- Caching Configuration ---
cache_config = {
    'CACHE_TYPE': 'simple',  # Use 'redis' for production
    'CACHE_DEFAULT_TIMEOUT': 300,  # 5 minutes default
}
cache = Cache(app, config=cache_config)

# --- CORS Configuration ---
CORS(app, resources={r"/api/*": {"origins": "*"}})

# --- Firebase Initialization ---
FIREBASE_SERVICE_ACCOUNT_KEY_PATH = os.getenv("FIREBASE_SERVICE_ACCOUNT_KEY_PATH")

if not FIREBASE_SERVICE_ACCOUNT_KEY_PATH:
    app.logger.critical("FIREBASE_SERVICE_ACCOUNT_KEY_PATH environment variable not set. Exiting.")
    raise EnvironmentError("FIREBASE_SERVICE_ACCOUNT_KEY_PATH environment variable not set.")

try:
    #cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT_KEY_PATH)
    firebase_admin.initialize_app()
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

# --- Leaderboard API Route (unchanged) ---
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

# --- Player Odds API Route (MODIFIED) ---
@app.route('/api/player_odds', methods=['GET'])
def get_player_odds():
    odds_id = request.args.get('oddsId')
    if not odds_id:
        app.logger.error("Missing 'oddsId' parameter for player odds API.")
        return jsonify({"error": "Missing oddsId parameter"}), 400

    # NEW: Check if the draft has started and locked odds are available in Firestore
    try:
        # Find the tournament by oddsId (assuming oddsId is unique per tournament)
        tournaments_ref = db.collection('tournaments').where('oddsId', '==', odds_id).limit(1).get()
        tournament_doc = None
        for doc in tournaments_ref: # Iterate to get the single document
            tournament_doc = doc
            break

        if tournament_doc and tournament_doc.exists:
            tournament_data = tournament_doc.to_dict()
            if tournament_data.get('IsDraftStarted') and tournament_data.get('DraftLockedOdds'):
                app.logger.info(f"Returning LOCKED draft odds for tournament with oddsId: {odds_id}")
                return jsonify(tournament_data['DraftLockedOdds'])

    except Exception as e:
        app.logger.error(f"Error checking Firestore for locked odds for oddsId {odds_id}: {e}")
        # Continue to fetch live if Firestore check fails

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

# --- Global Teams Management API Routes ---

@app.route('/api/global_teams', methods=['GET'])
def get_global_teams():
    """Get all global teams"""
    if not db:
        app.logger.error("Firestore DB not initialized.")
        return jsonify({"error": "Firestore not initialized"}), 500
    try:
        teams_ref = db.collection('global_teams').order_by('name').get()
        teams_list = []
        for doc in teams_ref:
            team_data = doc.to_dict()
            teams_list.append({
                "id": doc.id,
                **team_data
            })
        return jsonify(teams_list), 200
    except Exception as e:
        app.logger.error(f"Error fetching global teams: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/global_teams', methods=['POST'])
def create_global_team():
    """Create a new global team"""
    if not db:
        app.logger.error("Firestore DB not initialized.")
        return jsonify({"error": "Firestore not initialized"}), 500
    try:
        data = request.json
        if not data or 'name' not in data:
            return jsonify({"error": "Missing 'name' for new team"}), 400

        team_name = data['name'].strip()
        if not team_name:
            return jsonify({"error": "Team name cannot be empty"}), 400

        # Check if team name already exists
        existing_teams = db.collection('global_teams').where('name', '==', team_name).limit(1).get()
        if len(list(existing_teams)) > 0:
            return jsonify({"error": "Team name already exists"}), 409

        new_team_data = {
            "name": team_name,
            "golferNames": data.get('golferNames', []),
            "participatesInAnnual": data.get('participatesInAnnual', True),
            "draftOrder": data.get('draftOrder', 0),
            "createdAt": firestore.SERVER_TIMESTAMP
        }
        
        doc_ref = db.collection('global_teams').add(new_team_data)
        return jsonify({"message": "Global team created successfully", "id": doc_ref[1].id, "name": team_name}), 201
    except Exception as e:
        app.logger.error(f"Error creating global team: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/global_teams/<team_id>', methods=['PUT'])
def update_global_team(team_id):
    """Update a global team"""
    if not db:
        app.logger.error("Firestore DB not initialized.")
        return jsonify({"error": "Firestore not initialized"}), 500
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No data provided"}), 400

        doc_ref = db.collection('global_teams').document(team_id)
        doc = doc_ref.get()
        if not doc.exists:
            return jsonify({"error": "Team not found"}), 404

        # Prepare update data
        update_data = {}
        if 'name' in data:
            team_name = data['name'].strip()
            if not team_name:
                return jsonify({"error": "Team name cannot be empty"}), 400
            # Check if new name conflicts with existing teams (excluding current team)
            existing_teams = db.collection('global_teams').where('name', '==', team_name).get()
            for existing_doc in existing_teams:
                if existing_doc.id != team_id:
                    return jsonify({"error": "Team name already exists"}), 409
            update_data['name'] = team_name

        if 'golferNames' in data:
            update_data['golferNames'] = data['golferNames']
        if 'participatesInAnnual' in data:
            update_data['participatesInAnnual'] = data['participatesInAnnual']
        if 'draftOrder' in data:
            update_data['draftOrder'] = data['draftOrder']

        update_data['updatedAt'] = firestore.SERVER_TIMESTAMP
        doc_ref.update(update_data)
        
        return jsonify({"message": f"Global team {team_id} updated successfully"}), 200
    except Exception as e:
        app.logger.error(f"Error updating global team {team_id}: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/global_teams/<team_id>', methods=['DELETE'])
def delete_global_team(team_id):
    """Delete a global team"""
    if not db:
        app.logger.error("Firestore DB not initialized.")
        return jsonify({"error": "Firestore not initialized"}), 500
    try:
        doc_ref = db.collection('global_teams').document(team_id)
        doc = doc_ref.get()
        if not doc.exists:
            return jsonify({"error": "Team not found"}), 404

        doc_ref.delete()
        return jsonify({"message": f"Global team {team_id} deleted successfully"}), 200
    except Exception as e:
        app.logger.error(f"Error deleting global team {team_id}: {e}")
        return jsonify({"error": str(e)}), 500

# --- Tournament Team Assignment API Routes ---

@app.route('/api/tournaments/<tournament_id>/team_assignments', methods=['GET'])
def get_tournament_team_assignments(tournament_id):
    """Get team assignments for a tournament"""
    if not db:
        app.logger.error("Firestore DB not initialized.")
        return jsonify({"error": "Firestore not initialized"}), 500
    try:
        doc_ref = db.collection('tournaments').document(tournament_id)
        doc = doc_ref.get()
        if not doc.exists:
            return jsonify({"error": "Tournament not found"}), 404
        
        tournament_data = doc.to_dict()
        team_assignments = tournament_data.get('teamAssignments', [])
        return jsonify(team_assignments), 200
    except Exception as e:
        app.logger.error(f"Error fetching team assignments for tournament {tournament_id}: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/tournaments/<tournament_id>/team_assignments', methods=['PUT'])
def update_tournament_team_assignments(tournament_id):
    """Update team assignments for a tournament (which global teams participate)"""
    if not db:
        app.logger.error("Firestore DB not initialized.")
        return jsonify({"error": "Firestore not initialized"}), 500
    try:
        data = request.json
        if not data or 'teamAssignments' not in data:
            return jsonify({"error": "Missing 'teamAssignments' in request data"}), 400

        doc_ref = db.collection('tournaments').document(tournament_id)
        doc = doc_ref.get()
        if not doc.exists:
            return jsonify({"error": "Tournament not found"}), 404

        # Validate that all referenced team IDs exist in global_teams
        team_assignments = data['teamAssignments']
        if team_assignments:
            team_ids = [assignment.get('globalTeamId') for assignment in team_assignments if assignment.get('globalTeamId')]
            if team_ids:
                existing_teams = db.collection('global_teams').where('__name__', 'in', team_ids).get()
                existing_team_ids = {doc.id for doc in existing_teams}
                missing_teams = set(team_ids) - existing_team_ids
                if missing_teams:
                    return jsonify({"error": f"Referenced teams not found: {list(missing_teams)}"}), 400

        doc_ref.update({
            "teamAssignments": team_assignments,
            "updatedAt": firestore.SERVER_TIMESTAMP
        })
        return jsonify({"message": f"Team assignments for tournament {tournament_id} updated successfully"}), 200
    except Exception as e:
        app.logger.error(f"Error updating team assignments for tournament {tournament_id}: {e}")
        return jsonify({"error": str(e)}), 500

# --- Tournament Management API Routes (MODIFIED) ---

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
            "teams": [],  # Legacy field for backward compatibility
            "teamAssignments": [],  # New field for global team references
            "IsDraftStarted": False, # NEW: Initialize IsDraftStarted to false
            "IsDraftComplete": False, # NEW: Initialize IsDraftComplete to false
            "DraftLockedOdds": [],   # NEW: Initialize empty array for locked odds
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

        # Combine logic: Frontend should show leaderboard if in progress OR over
        show_leaderboard_on_frontend = is_in_progress_from_api or is_over_from_api

        # Combine Firestore data with the live status and potential updated Par
        response_data = {
            "id": doc.id,
            **tournament_data,
            "IsInProgress": show_leaderboard_on_frontend,
            "IsOver": is_over_from_api,
            "par": tournament_par,
            "IsDraftStarted": tournament_data.get('IsDraftStarted', False),
            "Tournament": odds_api_data.get("Tournament", {}),
            "status": odds_api_data.get("Tournament", {}).get("Status", "")
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
        
        # Optional: Normalize teams data to ensure participatesInAnnual field exists
        # and validate draft order uniqueness and range
        normalized_teams = []
        draft_orders = []
        
        for team in data['teams']:
            if isinstance(team, dict):
                # Ensure participatesInAnnual field exists (default to True for backward compatibility)
                if 'participatesInAnnual' not in team:
                    team['participatesInAnnual'] = True
                    
                # Validate draft order
                if 'draftOrder' in team and team['draftOrder'] is not None:
                    draft_order = team['draftOrder']
                    if not isinstance(draft_order, int) or draft_order < 1:
                        return jsonify({"error": f"Invalid draft order for team {team.get('name', 'Unknown')}: {draft_order}. Must be a positive integer."}), 400
                    if draft_order in draft_orders:
                        return jsonify({"error": f"Duplicate draft order: {draft_order}. Each team must have a unique draft order."}), 400
                    draft_orders.append(draft_order)
                    
                normalized_teams.append(team)
            else:
                normalized_teams.append(team)  # Keep non-dict items as-is for flexibility
        
        # Check for gaps in draft order sequence (optional strict validation)
        if draft_orders:
            draft_orders.sort()
            expected_max = len([team for team in data['teams'] if team.get('draftOrder') is not None])
            if draft_orders[-1] > expected_max:
                app.logger.warning(f"Draft order gap detected. Highest order: {draft_orders[-1]}, Expected max: {expected_max}")
        
        doc_ref = db.collection('tournaments').document(tournament_id)
        doc = doc_ref.get()
        if not doc.exists:
            return jsonify({"error": "Tournament not found"}), 404
        doc_ref.update({"teams": normalized_teams})
        return jsonify({"message": f"Teams for tournament {tournament_id} updated successfully"}), 200
    except Exception as e:
        app.logger.error(f"Error updating teams for tournament {tournament_id}: {e}")
        return jsonify({"error": str(e)}), 500

# NEW: API endpoint to start the draft and lock in odds
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
            return jsonify({"message": "Draft has already started for this tournament."}), 409 # Conflict

        odds_id = tournament_data.get("oddsId")
        if not odds_id:
            return jsonify({"error": "Tournament does not have an Odds ID configured."}), 400

        # Fetch current live player odds
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

            # Store the locked odds and set the flag
            doc_ref.update({
                "IsDraftStarted": True,
                "DraftLockedOdds": averaged_odds_list,
                "DraftStartedAt": firestore.SERVER_TIMESTAMP # Optional: Timestamp when draft started
            })

            return jsonify({"message": f"Draft started and odds locked for tournament {tournament_id}."}), 200

        except requests.exceptions.RequestException as e:
            app.logger.error(f"Error fetching live odds to lock in from SportsData.io for oddsId {odds_id}: {e}")
            details = str(e)
            if e.response is not None:
                details += f" | Status: {e.response.status_code} | Content: {e.response.text}"
            return jsonify({"error": f"Failed to fetch live odds to lock in: {details}"}), 500
        except ValueError:
            app.logger.error("Failed to parse JSON response from SportsData.io (locking odds) for oddsId %s", odds_id)
            return jsonify({"error": "Invalid JSON response from external API when locking odds."}), 500

    except Exception as e:
        app.logger.error(f"Error starting draft for tournament {tournament_id}: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/tournaments/<tournament_id>/start_draft_flag', methods=['POST'])
def start_draft_flag(tournament_id):
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
        doc_ref.update({
            "IsDraftStarted": True,
            "DraftStartedAt": firestore.SERVER_TIMESTAMP
        })
        return jsonify({"message": f"Draft started for tournament {tournament_id}."}), 200
    except Exception as e:
        app.logger.error(f"Error starting draft flag for tournament {tournament_id}: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/tournaments/<tournament_id>/lock_draft_odds', methods=['POST'])
def lock_draft_odds(tournament_id):
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
        if not odds_id:
            return jsonify({"error": "Tournament does not have an Odds ID configured."}), 400
        dynamic_odds_api_endpoint = f"https://api.sportsdata.io/v3/golf/odds/json/TournamentOdds/{odds_id}"
        headers = {
            "Ocp-Apim-Subscription-Key": SPORTSDATA_IO_API_KEY
        }
        response = requests.get(dynamic_odds_api_endpoint, headers=headers)
        response.raise_for_status()
        data = response.json()
        if not data or not data.get("PlayerTournamentOdds"):
            return jsonify({"error": "Could not retrieve live odds to lock in. API response missing player data."}), 500
        raw_player_odds = data["PlayerTournamentOdds"]
        averaged_odds_list = calculate_average_odds(raw_player_odds)
        doc_ref.update({
            "DraftLockedOdds": averaged_odds_list,
            "DraftOddsLockedAt": firestore.SERVER_TIMESTAMP
        })
        return jsonify({"message": f"Draft odds locked for tournament {tournament_id}."}), 200
    except Exception as e:
        app.logger.error(f"Error locking draft odds for tournament {tournament_id}: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/tournaments/<tournament_id>/draft_status', methods=['GET'])
def get_draft_status(tournament_id):
    if not db:
        app.logger.error("Firestore DB not initialized.")
        return jsonify({"error": "Firestore not initialized"}), 500
    try:
        doc_ref = db.collection('tournaments').document(tournament_id)
        doc = doc_ref.get()
        if not doc.exists:
            return jsonify({"error": "Tournament not found"}), 404
        tournament_data = doc.to_dict()
        is_draft_started = tournament_data.get('IsDraftStarted', False)
        draft_locked_odds = tournament_data.get('DraftLockedOdds', [])
        is_draft_locked = bool(draft_locked_odds and len(draft_locked_odds) > 0)
        is_draft_complete = tournament_data.get('IsDraftComplete', False)
        return jsonify({
            "IsDraftStarted": is_draft_started,
            "IsDraftLocked": is_draft_locked,
            "IsDraftComplete": is_draft_complete
        }), 200
    except Exception as e:
        app.logger.error(f"Error fetching draft status for tournament {tournament_id}: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/tournaments/<tournament_id>/complete_draft', methods=['POST'])
def complete_draft(tournament_id):
    if not db:
        app.logger.error("Firestore DB not initialized.")
        return jsonify({"error": "Firestore not initialized"}), 500
    try:
        doc_ref = db.collection('tournaments').document(tournament_id)
        doc = doc_ref.get()
        if not doc.exists:
            return jsonify({"error": "Tournament not found"}), 404
        doc_ref.update({
            "IsDraftComplete": True,
            "DraftCompletedAt": firestore.SERVER_TIMESTAMP
        })
        return jsonify({"message": f"Draft marked complete for tournament {tournament_id}."}), 200
    except Exception as e:
        app.logger.error(f"Error marking draft complete for tournament {tournament_id}: {e}")
        return jsonify({"error": str(e)}), 500

# NEW: API endpoint to get draft order information
@app.route('/api/tournaments/<tournament_id>/draft_order', methods=['GET'])
def get_draft_order(tournament_id):
    if not db:
        app.logger.error("Firestore DB not initialized.")
        return jsonify({"error": "Firestore not initialized"}), 500
    try:
        doc_ref = db.collection('tournaments').document(tournament_id)
        doc = doc_ref.get()
        if not doc.exists:
            return jsonify({"error": "Tournament not found"}), 404
        
        tournament_data = doc.to_dict()
        teams = tournament_data.get('teams', [])
        
        # Extract draft order information
        draft_order_info = []
        for team in teams:
            if 'draftOrder' in team and team['draftOrder'] is not None:
                team_info = {
                    'name': team.get('name', 'Unknown'),
                    'draftOrder': team['draftOrder'],
                    'playersCount': len(team.get('players', [])),
                    'id': team.get('id')
                }
                draft_order_info.append(team_info)
        
        # Sort by draft order
        draft_order_info.sort(key=lambda x: x['draftOrder'])
        
        return jsonify({
            "draftOrder": draft_order_info,
            "totalTeams": len(draft_order_info),
            "isDraftStarted": tournament_data.get('IsDraftStarted', False),
            "isDraftComplete": tournament_data.get('IsDraftComplete', False)
        }), 200
        
    except Exception as e:
        app.logger.error(f"Error fetching draft order for tournament {tournament_id}: {e}")
        return jsonify({"error": str(e)}), 500

# --- Performance Monitoring Utilities ---
def performance_monitor(func):
    """Decorator to monitor function performance"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            duration = time.time() - start_time
            app.logger.info(f"{func.__name__} completed in {duration:.3f}s")
            return result
        except Exception as e:
            duration = time.time() - start_time
            app.logger.error(f"{func.__name__} failed after {duration:.3f}s: {str(e)}")
            raise
    return wrapper

def cache_key_generator(*args, **kwargs):
    """Generate cache key from function arguments"""
    key_data = str(args) + str(sorted(kwargs.items()))
    return hashlib.md5(key_data.encode()).hexdigest()

def smart_cache(timeout=300, key_prefix=''):
    """Smart caching decorator with dynamic key generation"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = f"{key_prefix}:{func.__name__}:{cache_key_generator(*args, **kwargs)}"
            result = cache.get(cache_key)
            
            if result is None:
                result = func(*args, **kwargs)
                cache.set(cache_key, result, timeout=timeout)
                app.logger.debug(f"Cache MISS for {cache_key}")
            else:
                app.logger.debug(f"Cache HIT for {cache_key}")
            
            return result
        return wrapper
    return decorator

# --- Response Optimization ---
def optimize_response(data, request_args=None):
    """Optimize response data based on request parameters"""
    if not request_args:
        return data
    
    # Implement field filtering
    fields = request_args.get('fields')
    if fields:
        field_list = fields.split(',')
        if isinstance(data, list):
            data = [{k: v for k, v in item.items() if k in field_list} for item in data]
        elif isinstance(data, dict):
            data = {k: v for k, v in data.items() if k in field_list}
    
    # Implement pagination
    page = request_args.get('page', type=int)
    per_page = request_args.get('per_page', type=int, default=50)
    
    if page and isinstance(data, list):
        start = (page - 1) * per_page
        end = start + per_page
        data = data[start:end]
    
    return data

# --- Batch API Endpoint ---
@app.route('/api/batch', methods=['POST'])
@performance_monitor
def batch_requests():
    """Handle multiple API requests in a single call"""
    try:
        requests_data = request.get_json()
        if not requests_data or 'requests' not in requests_data:
            return jsonify({'error': 'Invalid batch request format'}), 400
        
        requests_list = requests_data['requests']
        if len(requests_list) > 10:  # Limit batch size
            return jsonify({'error': 'Too many requests in batch (max 10)'}), 400
        
        results = []
        
        for req_data in requests_list:
            try:
                endpoint = req_data.get('endpoint', '')
                params = req_data.get('params', {})
                
                # Route to appropriate handler based on endpoint
                if endpoint.startswith('/tournaments'):
                    if '/leaderboard' in endpoint:
                        tournament_id = endpoint.split('/')[-2]
                        # Call leaderboard logic (would need to extract from existing endpoint)
                        result = {'message': 'Leaderboard data would be fetched here'}
                    elif '/draft_status' in endpoint:
                        tournament_id = endpoint.split('/')[-2]
                        # Call draft status logic
                        result = {'message': 'Draft status would be fetched here'}
                    else:
                        tournament_id = endpoint.split('/')[-1]
                        # Call tournament data logic
                        result = {'message': 'Tournament data would be fetched here'}
                elif endpoint.startswith('/player_odds'):
                    odds_id = params.get('oddsId')
                    # Call player odds logic
                    result = {'message': 'Player odds would be fetched here'}
                else:
                    result = {'error': f'Unknown endpoint: {endpoint}'}
                
                results.append({'data': result, 'error': None})
                
            except Exception as e:
                results.append({'data': None, 'error': str(e)})
        
        return jsonify(results)
        
    except Exception as e:
        app.logger.error(f"Batch request error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

# --- Database Optimization ---
class FirestoreOptimizer:
    def __init__(self, db_client):
        self.db = db_client
        self.query_cache = {}
    
    @smart_cache(timeout=600, key_prefix='firestore')
    def get_tournament_cached(self, tournament_id):
        """Get tournament with caching"""
        try:
            doc_ref = self.db.collection('tournaments').document(tournament_id)
            doc = doc_ref.get()
            
            if doc.exists:
                return doc.to_dict()
            return None
        except Exception as e:
            app.logger.error(f"Error fetching tournament {tournament_id}: {str(e)}")
            return None
    
    @smart_cache(timeout=300, key_prefix='firestore')
    def get_tournaments_list_cached(self):
        """Get tournaments list with caching"""
        try:
            tournaments_ref = self.db.collection('tournaments')
            docs = tournaments_ref.stream()
            
            tournaments = []
            for doc in docs:
                tournament_data = doc.to_dict()
                tournament_data['id'] = doc.id
                tournaments.append(tournament_data)
            
            return tournaments
        except Exception as e:
            app.logger.error(f"Error fetching tournaments list: {str(e)}")
            return []
    
    def batch_update_tournaments(self, updates):
        """Perform batch updates for better performance"""
        try:
            batch = self.db.batch()
            
            for tournament_id, update_data in updates.items():
                doc_ref = self.db.collection('tournaments').document(tournament_id)
                batch.update(doc_ref, update_data)
            
            batch.commit()
            
            # Clear related cache
            cache.delete_memoized(self.get_tournament_cached)
            cache.delete_memoized(self.get_tournaments_list_cached)
            
            return True
        except Exception as e:
            app.logger.error(f"Batch update failed: {str(e)}")
            return False

# Initialize database optimizer
if db:
    db_optimizer = FirestoreOptimizer(db)
else:
    db_optimizer = None

# --- Flask App Run ---
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
