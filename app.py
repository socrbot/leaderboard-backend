import os
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_compress import Compress
from flask_caching import Cache
from dotenv import load_dotenv
import time
import json
from datetime import datetime, timedelta
import hashlib
import functools
import logging
from threading import Lock
import schedule
import threading

# --- Firebase Admin SDK Imports ---
import firebase_admin
from firebase_admin import credentials, firestore

# Load environment variables from .env file (only for local development)
# load_dotenv()

app = Flask(__name__)

# --- Logging Configuration ---
logging.basicConfig(level=logging.INFO)
app.logger.setLevel(logging.INFO)

# --- Compression Configuration ---
Compress(app)

# --- Advanced Caching Configuration ---
cache_config = {
    'CACHE_TYPE': 'simple',  # Use 'redis' for production
    'CACHE_DEFAULT_TIMEOUT': 300,  # 5 minutes default
}
cache = Cache(app, config=cache_config)

# --- CORS Configuration ---
CORS(app, resources={r"/api/*": {"origins": "*"}})

# --- RapidAPI Configuration ---
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
RAPIDAPI_HOST = "live-golf-data.p.rapidapi.com"
RAPIDAPI_BASE_URL = "https://live-golf-data.p.rapidapi.com"

# --- API Rate Limiting Configuration ---
API_CALL_LOCK = Lock()
API_CALL_LOG = []  # Track API calls for rate limiting
MAX_DAILY_CALLS = 20
MAX_MONTHLY_CALLS = 200
CALL_INTERVAL_MINUTES = 45  # 45 minutes between calls for optimal distribution

# --- Tournament Status Constants ---
TOURNAMENT_STATUS = {
    'NOT_STARTED': 'Not Started',
    'IN_PROGRESS': 'In Progress',
    'COMPLETE': 'Complete',
    'OFFICIAL': 'Official'
}

COMPLETED_STATUSES = [TOURNAMENT_STATUS['COMPLETE'], TOURNAMENT_STATUS['OFFICIAL']]
ACTIVE_STATUSES = [TOURNAMENT_STATUS['IN_PROGRESS']]

# --- Cache TTL Configuration ---
CACHE_TTL_SECONDS = 5 * 60  # 5 minutes for general data
TOURNAMENT_CACHE_TTL = 10 * 60  # 10 minutes for tournament data
LEADERBOARD_CACHE_TTL = 3 * 60  # 3 minutes for live leaderboard data

# --- Firebase Initialization ---
FIREBASE_SERVICE_ACCOUNT_KEY_PATH = os.getenv("FIREBASE_SERVICE_ACCOUNT_KEY_PATH")

# Initialize Firebase
db = None
if not FIREBASE_SERVICE_ACCOUNT_KEY_PATH:
    app.logger.critical("FIREBASE_SERVICE_ACCOUNT_KEY_PATH environment variable not set. Exiting.")
    raise EnvironmentError("FIREBASE_SERVICE_ACCOUNT_KEY_PATH environment variable not set.")
else:
    try:
        #cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT_KEY_PATH)
        firebase_admin.initialize_app()
        db = firestore.client()
        app.logger.info("Firebase Admin SDK initialized successfully.")
    except Exception as e:
        app.logger.error(f"Error initializing Firebase Admin SDK: {e}")
        raise

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

# --- API Rate Limiting Functions ---
def log_api_call():
    """Log an API call for rate limiting tracking"""
    with API_CALL_LOCK:
        now = datetime.now()
        API_CALL_LOG.append(now)
        # Clean up old entries (older than 24 hours)
        cutoff = now - timedelta(hours=24)
        API_CALL_LOG[:] = [call_time for call_time in API_CALL_LOG if call_time > cutoff]

def check_rate_limit():
    """Check if we can make an API call within rate limits"""
    with API_CALL_LOCK:
        now = datetime.now()
        # Clean up old entries
        cutoff_daily = now - timedelta(hours=24)
        cutoff_monthly = now - timedelta(days=30)
        
        daily_calls = len([call_time for call_time in API_CALL_LOG if call_time > cutoff_daily])
        monthly_calls = len([call_time for call_time in API_CALL_LOG if call_time > cutoff_monthly])
        
        return daily_calls < MAX_DAILY_CALLS and monthly_calls < MAX_MONTHLY_CALLS

def get_rate_limit_status():
    """Get current rate limit status"""
    with API_CALL_LOCK:
        now = datetime.now()
        cutoff_daily = now - timedelta(hours=24)
        cutoff_monthly = now - timedelta(days=30)
        
        daily_calls = len([call_time for call_time in API_CALL_LOG if call_time > cutoff_daily])
        monthly_calls = len([call_time for call_time in API_CALL_LOG if call_time > cutoff_monthly])
        
        return {
            'daily_calls': daily_calls,
            'monthly_calls': monthly_calls,
            'daily_limit': MAX_DAILY_CALLS,
            'monthly_limit': MAX_MONTHLY_CALLS,
            'can_make_call': daily_calls < MAX_DAILY_CALLS and monthly_calls < MAX_MONTHLY_CALLS
        }

# --- Tournament Status Detection Functions ---
def get_tournament_status_from_api(api_response):
    """Extract tournament status from RapidAPI response"""
    try:
        # Check main tournament status
        status = api_response.get('status', '').strip()
        round_status = api_response.get('roundStatus', '').strip()
        round_id = api_response.get('roundId')
        last_updated = api_response.get('lastUpdated', '')
        
        # Determine if tournament is officially complete
        is_official_complete = status == TOURNAMENT_STATUS['OFFICIAL']
        is_in_progress = status in ACTIVE_STATUSES
        
        return {
            'status': status,
            'roundStatus': round_status,
            'roundId': round_id,
            'lastUpdated': last_updated,
            'isOfficialComplete': is_official_complete,
            'isInProgress': is_in_progress
        }
    except Exception as e:
        app.logger.error(f"Error parsing tournament status: {e}")
        return {
            'status': 'Unknown',
            'roundStatus': 'Unknown',
            'roundId': None,
            'lastUpdated': '',
            'isOfficialComplete': False,
            'isInProgress': False
        }

# --- Persistent Score Storage Functions ---
def store_calculated_scores(tournament_id, leaderboard_data, team_scores, metadata):
    """Store calculated team scores in Firestore for persistence"""
    if not db:
        return False
    
    try:
        # Create score snapshot document
        score_snapshot = {
            'tournamentId': tournament_id,
            'leaderboardData': leaderboard_data,
            'teamScores': team_scores,
            'metadata': metadata,
            'calculatedAt': firestore.SERVER_TIMESTAMP,
            'tournamentStatus': leaderboard_data.get('tournamentStatus', {}),
            'isOfficialComplete': leaderboard_data.get('isOfficiallyComplete', False),
            'roundId': leaderboard_data.get('roundId'),
            'dataHash': hashlib.md5(str(leaderboard_data.get('leaderboardRows', [])).encode()).hexdigest()
        }
        
        # Store in tournament_scores collection
        doc_ref = db.collection('tournament_scores').document(f"{tournament_id}_latest")
        doc_ref.set(score_snapshot)
        
        # Also store in tournament document for easy access
        tournament_ref = db.collection('tournaments').document(tournament_id)
        tournament_ref.update({
            'lastCalculatedScores': team_scores,
            'lastScoreCalculation': firestore.SERVER_TIMESTAMP,
            'lastScoreMetadata': metadata
        })
        
        app.logger.info(f"Stored calculated scores for tournament {tournament_id}")
        return True
        
    except Exception as e:
        app.logger.error(f"Error storing calculated scores: {e}")
        return False

def get_stored_scores(tournament_id, max_age_minutes=45):
    """Retrieve stored team scores if they're recent enough (aligned with 45-min tournament schedule)"""
    if not db:
        return None
    
    try:
        # Check tournament document first (fastest)
        tournament_ref = db.collection('tournaments').document(tournament_id)
        tournament_doc = tournament_ref.get()
        
        if tournament_doc.exists:
            tournament_data = tournament_doc.to_dict()
            last_calculation = tournament_data.get('lastScoreCalculation')
            
            if last_calculation:
                # Check if calculation is recent enough (45-min aligns with tournament schedule)
                time_diff = datetime.now() - last_calculation.replace(tzinfo=None)
                if time_diff.total_seconds() < (max_age_minutes * 60):
                    stored_scores = tournament_data.get('lastCalculatedScores')
                    if stored_scores:
                        app.logger.info(f"Using stored scores for tournament {tournament_id} (age: {time_diff.total_seconds():.0f}s)")
                        return {
                            'teamScores': stored_scores,
                            'metadata': tournament_data.get('lastScoreMetadata', {}),
                            'fromStorage': True,
                            'calculatedAt': last_calculation.isoformat(),
                            'dataSource': 'scheduled_update' if time_diff.total_seconds() < 2700 else 'cached_calculation'  # 45 min = 2700 sec
                        }
        
        # Fallback to detailed score snapshot
        score_doc_ref = db.collection('tournament_scores').document(f"{tournament_id}_latest")
        score_doc = score_doc_ref.get()
        
        if score_doc.exists:
            score_data = score_doc.to_dict()
            calculated_at = score_data.get('calculatedAt')
            
            if calculated_at:
                time_diff = datetime.now() - calculated_at.replace(tzinfo=None)
                if time_diff.total_seconds() < (max_age_minutes * 60):
                    app.logger.info(f"Using detailed stored scores for tournament {tournament_id}")
                    return {
                        'teamScores': score_data.get('teamScores', []),
                        'leaderboardData': score_data.get('leaderboardData', {}),
                        'metadata': score_data.get('metadata', {}),
                        'fromStorage': True,
                        'calculatedAt': calculated_at.isoformat(),
                        'dataSource': 'detailed_snapshot'
                    }
        
        return None
        
    except Exception as e:
        app.logger.error(f"Error retrieving stored scores: {e}")
        return None

def should_recalculate_scores(tournament_id, current_leaderboard_data):
    """Determine if scores need recalculation based on data changes"""
    if not db:
        return True
    
    try:
        score_doc_ref = db.collection('tournament_scores').document(f"{tournament_id}_latest")
        score_doc = score_doc_ref.get()
        
        if not score_doc.exists:
            return True
        
        stored_data = score_doc.to_dict()
        stored_hash = stored_data.get('dataHash')
        current_hash = hashlib.md5(str(current_leaderboard_data.get('leaderboardRows', [])).encode()).hexdigest()
        
        # Recalculate if data has changed
        if stored_hash != current_hash:
            app.logger.info(f"Leaderboard data changed for tournament {tournament_id}, recalculating scores")
            return True
        
        # Recalculate if tournament status changed to official
        current_status = current_leaderboard_data.get('tournamentStatus', {})
        stored_status = stored_data.get('tournamentStatus', {})
        
        if (current_status.get('isOfficialComplete') and 
            not stored_status.get('isOfficialComplete')):
            app.logger.info(f"Tournament {tournament_id} became official, recalculating final scores")
            return True
        
        return False
        
    except Exception as e:
        app.logger.error(f"Error checking if recalculation needed: {e}")
        return True

def parse_numeric_score(score_str):
    """Parse score string to numeric value"""
    if score_str in ["E", "e", None, ""]:
        return 0
    try:
        return float(score_str)
    except (ValueError, TypeError):
        return 0

def get_golfer_round_score(player, round_num, current_par):
    """Get a golfer's score for a specific round"""
    if player.get('rounds') and isinstance(player['rounds'], list):
        round_data = next((r for r in player['rounds'] 
                          if int(r.get('roundId', {}).get('$numberInt', r.get('roundId', 0))) == round_num), None)
        if round_data and round_data.get('strokes') is not None:
            strokes = round_data['strokes']
            if isinstance(strokes, dict) and '$numberInt' in strokes:
                strokes = strokes['$numberInt']
            return {'score': parse_numeric_score(strokes) - current_par, 'isLive': False}
    
    # Check current round
    current_round = player.get('currentRound')
    if isinstance(current_round, dict) and '$numberInt' in current_round:
        current_round = current_round['$numberInt']
    
    if (current_round == round_num and 
        player.get('currentRoundScore') is not None and 
        player.get('currentRoundScore') != ""):
        return {'score': parse_numeric_score(player['currentRoundScore']), 'isLive': True}
    
    return {'score': None, 'isLive': False}

def sum_best_n_scores(scores_array, n):
    """Sum the best N scores from an array"""
    valid_scores = []
    for score_obj in scores_array or []:
        if (score_obj and isinstance(score_obj, dict) and 
            isinstance(score_obj.get('score'), (int, float)) and 
            score_obj['score'] is not None):
            valid_scores.append(score_obj['score'])
    
    if len(valid_scores) < n:
        return None
    
    valid_scores.sort()
    return sum(valid_scores[:n])

def calculate_team_scores(players, team_assignments, current_par):
    """Calculate team scores with correct cut player penalty"""
    teams_map = {}
    
    # First, find the highest scoring non-cut player for penalty calculation
    highest_non_cut_score = None
    for player in players or []:
        if player.get('status') != 'cut' and player.get('total') is not None:
            player_total = parse_numeric_score(player.get('total'))
            if highest_non_cut_score is None or player_total > highest_non_cut_score:
                highest_non_cut_score = player_total
    
    # If no non-cut players found, use a default penalty score
    cut_penalty_score = (highest_non_cut_score + 1) if highest_non_cut_score is not None else 10
    
    for team_def in team_assignments or []:
        team_players = []
        team_rounds_relative = {'r1': [], 'r2': [], 'r3': [], 'r4': []}
        
        for golfer_name in team_def.get('golferNames', []):
            normalized_name = golfer_name.strip().lower()
            found_player = next((p for p in players or [] 
                               if f"{p.get('firstName', '')} {p.get('lastName', '')}".strip().lower() == normalized_name), None)
            
            if found_player:
                player_status = found_player.get('status', 'N/A')
                is_cut = player_status.lower() == 'cut'
                
                # For cut players, use penalty score for rounds they didn't complete
                golfer_round_scores = {}
                for round_num in [1, 2, 3, 4]:
                    round_key = f'r{round_num}'
                    round_score = get_golfer_round_score(found_player, round_num, current_par)
                    
                    # If player is cut and didn't play this round, assign penalty score
                    if is_cut and round_score['score'] is None:
                        round_score = {'score': cut_penalty_score, 'isLive': False, 'isPenalty': True}
                    else:
                        round_score['isPenalty'] = False
                    
                    golfer_round_scores[round_key] = round_score
                
                processed_player = {
                    'name': f"{found_player.get('firstName', '')} {found_player.get('lastName', '')}".strip(),
                    'status': player_status,
                    'total': parse_numeric_score(found_player.get('total')) if not is_cut else cut_penalty_score,
                    'thru': found_player.get('thru', ''),
                    'isCut': is_cut,
                    'cutPenaltyScore': cut_penalty_score if is_cut else None,
                    **golfer_round_scores
                }
                team_players.append(processed_player)
                
                for round_key in team_rounds_relative:
                    team_rounds_relative[round_key].append(golfer_round_scores[round_key])
            else:
                # Add placeholder for missing player
                placeholder = {
                    'name': golfer_name,
                    'status': 'Missing',
                    'total': None,
                    'thru': '',
                    'isCut': False,
                    'cutPenaltyScore': None,
                    'r1': {'score': None, 'isLive': False, 'isPenalty': False},
                    'r2': {'score': None, 'isLive': False, 'isPenalty': False},
                    'r3': {'score': None, 'isLive': False, 'isPenalty': False},
                    'r4': {'score': None, 'isLive': False, 'isPenalty': False},
                }
                team_players.append(placeholder)
                
                for round_key in team_rounds_relative:
                    team_rounds_relative[round_key].append({'score': None, 'isLive': False, 'isPenalty': False})
        
        # Calculate team scores (best 3 of 4 players per round)
        team_total_score = 0
        valid_round_count = 0
        cut_players_count = sum(1 for p in team_players if p.get('isCut', False))
        penalty_strokes_applied = 0
        
        round_details = {}
        for round_key in ['r1', 'r2', 'r3', 'r4']:
            round_scores = team_rounds_relative[round_key]
            
            # Count penalty scores applied this round
            penalty_scores_this_round = sum(1 for score in round_scores 
                                          if score and score.get('isPenalty', False))
            penalty_strokes_applied += penalty_scores_this_round
            
            best_3_score = sum_best_n_scores(round_scores, 3)
            if best_3_score is not None:
                team_total_score += best_3_score
                valid_round_count += 1
                
            round_details[round_key] = {
                'score': best_3_score,
                'penaltyScores': penalty_scores_this_round,
                'validScores': len([s for s in round_scores if s and s.get('score') is not None])
            }
        
        teams_map[team_def.get('teamName', 'Unknown Team')] = {
            'teamName': team_def.get('teamName', 'Unknown Team'),
            'totalScore': team_total_score if valid_round_count > 0 else None,
            'players': team_players,
            'cutPlayersCount': cut_players_count,
            'penaltyStrokesApplied': penalty_strokes_applied,
            'cutPenaltyScore': cut_penalty_score,
            'highestNonCutScore': highest_non_cut_score,
            'validRounds': valid_round_count,
            'roundDetails': round_details
        }
    
    return list(teams_map.values())

# --- Optimized RapidAPI Integration Functions ---
def make_rapidapi_request(endpoint, params=None):
    """Make a rate-limited request to RapidAPI"""
    if not check_rate_limit():
        rate_status = get_rate_limit_status()
        app.logger.warning(f"Rate limit exceeded: {rate_status}")
        return None, f"Rate limit exceeded. Daily: {rate_status['daily_calls']}/{rate_status['daily_limit']}, Monthly: {rate_status['monthly_calls']}/{rate_status['monthly_limit']}"
    
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": RAPIDAPI_HOST
    }
    
    try:
        log_api_call()
        response = requests.get(f"{RAPIDAPI_BASE_URL}{endpoint}", headers=headers, params=params)
        response.raise_for_status()
        return response.json(), None
    except requests.exceptions.RequestException as e:
        error_msg = f"RapidAPI request failed: {e}"
        if hasattr(e, 'response') and e.response is not None:
            error_msg += f" | Status: {e.response.status_code} | Content: {e.response.text}"
        app.logger.error(error_msg)
        return None, error_msg

# --- Enhanced API Routes ---

@app.route('/api/rate_limit_status', methods=['GET'])
def get_api_rate_limit_status():
    """Get current API rate limit status"""
    return jsonify(get_rate_limit_status())

@app.route('/api/schedule', methods=['GET'])
@cache.cached(timeout=TOURNAMENT_CACHE_TTL)
def get_tournament_schedule():
    """Get PGA Tour schedule using RapidAPI"""
    year = request.args.get('year', '2025')
    org_id = request.args.get('orgId', '1')
    
    data, error = make_rapidapi_request('/schedule', {'year': year, 'orgId': org_id})
    if error:
        return jsonify({"error": error}), 429 if "Rate limit" in error else 500
    
    return jsonify(data)

@app.route('/api/tournament_info', methods=['GET'])
@cache.cached(timeout=TOURNAMENT_CACHE_TTL)
def get_tournament_info():
    """Get tournament information using RapidAPI"""
    org_id = request.args.get('orgId', '1')
    tourn_id = request.args.get('tournId')
    year = request.args.get('year', '2025')
    
    if not tourn_id:
        return jsonify({"error": "Missing required parameter: tournId"}), 400
    
    data, error = make_rapidapi_request('/tournament', {
        'orgId': org_id,
        'tournId': tourn_id,
        'year': year
    })
    if error:
        return jsonify({"error": error}), 429 if "Rate limit" in error else 500
    
    return jsonify(data)

@app.route('/api/leaderboard', methods=['GET'])
def get_optimized_leaderboard():
    """Get optimized leaderboard with team score calculations"""
    # Extract parameters
    org_id = request.args.get('orgId', '1')
    tourn_id = request.args.get('tournId', '033')
    year = request.args.get('year', '2025')
    round_id = request.args.get('roundId')  # Optional
    calculate_teams = request.args.get('calculateTeams', 'false').lower() == 'true'
    tournament_id = request.args.get('tournamentId')  # For team calculations
    
    # Create cache key
    cache_key_params = {
        'orgId': org_id,
        'tournId': tourn_id,
        'year': year,
        'roundId': round_id,
        'calculateTeams': calculate_teams,
        'tournamentId': tournament_id
    }
    cache_key = ('optimized_leaderboard', tuple(sorted(cache_key_params.items())))
    
    # Check cache
    if cache_key in CACHE:
        cached_data, timestamp = CACHE[cache_key]
        if (time.time() - timestamp) < LEADERBOARD_CACHE_TTL:
            app.logger.info("Returning cached leaderboard data")
            return jsonify(cached_data)
    
    # Prepare RapidAPI request parameters
    params = {'orgId': org_id, 'tournId': tourn_id, 'year': year}
    if round_id:
        params['roundId'] = round_id
    
    # Fetch leaderboard data
    data, error = make_rapidapi_request('/leaderboard', params)
    if error:
        return jsonify({"error": error}), 429 if "Rate limit" in error else 500
    
    # Add tournament status information
    tournament_status = get_tournament_status_from_api(data)
    enhanced_data = {
        **data,
        'tournamentStatus': tournament_status,
        'isOfficiallyComplete': tournament_status['isOfficialComplete']
    }
    
    # Calculate team scores if requested and tournament_id provided
    if calculate_teams and tournament_id and db:
        try:
            # First, check for stored scores
            stored_results = get_stored_scores(tournament_id, max_age_minutes=10)
            
            if stored_results and not should_recalculate_scores(tournament_id, enhanced_data):
                # Use stored scores
                app.logger.info(f"Using stored team scores for tournament {tournament_id}")
                enhanced_data['teamScores'] = stored_results['teamScores']
                enhanced_data['teamCalculationMetadata'] = {
                    **stored_results.get('metadata', {}),
                    'fromStorage': True,
                    'lastCalculated': stored_results.get('calculatedAt')
                }
            else:
                # Calculate fresh scores
                app.logger.info(f"Calculating fresh team scores for tournament {tournament_id}")
                doc_ref = db.collection('tournaments').document(tournament_id)
                doc = doc_ref.get()
                if doc.exists:
                    tournament_data = doc.to_dict()
                    team_assignments = tournament_data.get('teams', [])
                    current_par = tournament_data.get('par', 71)
                    
                    # Calculate team scores
                    leaderboard_rows = data.get('leaderboardRows', [])
                    team_scores = calculate_team_scores(leaderboard_rows, team_assignments, current_par)
                    
                    calculation_metadata = {
                        'par': current_par,
                        'teamCount': len(team_scores),
                        'playerCount': len(leaderboard_rows),
                        'calculatedAt': datetime.now().isoformat(),
                        'fromStorage': False
                    }
                    
                    enhanced_data['teamScores'] = team_scores
                    enhanced_data['teamCalculationMetadata'] = calculation_metadata
                    
                    # Store calculated scores for future use
                    store_calculated_scores(tournament_id, enhanced_data, team_scores, calculation_metadata)
                    
        except Exception as e:
            app.logger.error(f"Error calculating team scores: {e}")
            enhanced_data['teamCalculationError'] = str(e)
    
    # Cache the result
    CACHE[cache_key] = (enhanced_data, time.time())
    
    return jsonify(enhanced_data)

@app.route('/api/tournaments/<tournament_id>/leaderboard', methods=['GET'])
def get_tournament_leaderboard(tournament_id):
    """Get leaderboard data for a specific tournament (backwards compatibility)"""
    if not db:
        return jsonify({"error": "Firestore not initialized"}), 500
    
    try:
        # Get tournament details
        doc_ref = db.collection('tournaments').document(tournament_id)
        doc = doc_ref.get()
        
        if not doc.exists:
            return jsonify({'error': 'Tournament not found'}), 404
        
        tournament_data = doc.to_dict()
        
        # Extract tournament parameters
        org_id = tournament_data.get('orgId', '1')
        tourn_id = tournament_data.get('tournId')
        year = tournament_data.get('year', '2025')
        
        if not tourn_id:
            return jsonify({'error': 'Tournament missing required parameters'}), 400
        
        # Use the main leaderboard endpoint logic with tournament-specific parameters
        app.logger.info(f"Fetching leaderboard for tournament {tournament_id}: orgId={org_id}, tournId={tourn_id}, year={year}")
        
        # Directly call leaderboard logic with tournament parameters
        params = {'orgId': org_id, 'tournId': tourn_id, 'year': year}
        
        # Create cache key
        cache_key = ('tournament_leaderboard', tournament_id, org_id, tourn_id, year)
        
        # Check cache
        if cache_key in CACHE:
            cached_data, timestamp = CACHE[cache_key]
            if (time.time() - timestamp) < LEADERBOARD_CACHE_TTL:
                app.logger.info(f"Returning cached tournament leaderboard for {tournament_id}")
                return jsonify(cached_data)
        
        # Fetch leaderboard data from API
        data, error = make_rapidapi_request('/leaderboard', params)
        if error:
            return jsonify({"error": error}), 429 if "Rate limit" in error else 500
        
        # Add tournament status information
        tournament_status = get_tournament_status_from_api(data)
        enhanced_data = {
            **data,
            'tournamentStatus': tournament_status,
            'isOfficiallyComplete': tournament_status['isOfficialComplete']
        }
        
        # Always calculate team scores for tournament-specific requests
        try:
            # Check for stored scores first
            stored_results = get_stored_scores(tournament_id)
            
            if stored_results and not should_recalculate_scores(tournament_id, enhanced_data):
                # Use stored scores
                app.logger.info(f"Using stored team scores for tournament {tournament_id}")
                enhanced_data['teamScores'] = stored_results['teamScores']
                enhanced_data['teamCalculationMetadata'] = {
                    **stored_results.get('metadata', {}),
                    'fromStorage': True,
                    'lastCalculated': stored_results.get('calculatedAt')
                }
            else:
                # Calculate fresh scores
                app.logger.info(f"Calculating fresh team scores for tournament {tournament_id}")
                team_assignments = tournament_data.get('teams', [])
                current_par = tournament_data.get('par', 71)
                
                # Calculate team scores
                leaderboard_rows = data.get('leaderboardRows', [])
                team_scores = calculate_team_scores(leaderboard_rows, team_assignments, current_par)
                
                calculation_metadata = {
                    'par': current_par,
                    'teamCount': len(team_scores),
                    'playerCount': len(leaderboard_rows),
                    'calculatedAt': datetime.now().isoformat(),
                    'fromStorage': False
                }
                
                enhanced_data['teamScores'] = team_scores
                enhanced_data['teamCalculationMetadata'] = calculation_metadata
                
                # Store calculated scores for future use
                store_calculated_scores(tournament_id, enhanced_data, team_scores, calculation_metadata)
                
        except Exception as e:
            app.logger.error(f"Error calculating team scores for tournament {tournament_id}: {e}")
            enhanced_data['teamCalculationError'] = str(e)
        
        # Cache the result
        CACHE[cache_key] = (enhanced_data, time.time())
        
        return jsonify(enhanced_data)
        
    except Exception as e:
        app.logger.error(f"Error fetching tournament leaderboard for {tournament_id}: {e}")
        return jsonify({'error': str(e)}), 500

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

# --- Player Odds API Route (ENHANCED) ---
@app.route('/api/player_odds', methods=['GET'])
def get_player_odds():
    odds_id = request.args.get('oddsId')
    if not odds_id:
        app.logger.error("Missing 'oddsId' parameter for player odds API.")
        return jsonify({"error": "Missing oddsId parameter"}), 400

    # Check if the draft has started and locked odds are available in Firestore
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

    # Fetch fresh player odds from SportsData.io if not locked
    cache_key_params = request.args.to_dict()
    cache_key = ('player_odds', tuple(sorted(cache_key_params.items())))

    if cache_key in CACHE:
        cached_data, timestamp = CACHE[cache_key]
        if (time.time() - timestamp) < CACHE_TTL_SECONDS:
            app.logger.info("Returning cached data for player odds (live).")
            return jsonify(cached_data)

    app.logger.info("Fetching fresh player odds from SportsData.io.")
    dynamic_odds_api_endpoint = f"https://api.sportsdata.io/v3/golf/odds/json/TournamentOdds/{odds_id}"
    headers = {"Ocp-Apim-Subscription-Key": SPORTSDATA_IO_API_KEY}
    
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

# --- Annual Championship Calculation API ---
@app.route('/api/annual_championship', methods=['GET'])
@cache.cached(timeout=TOURNAMENT_CACHE_TTL)
def get_annual_championship():
    """Calculate annual championship standings from completed tournaments"""
    if not db:
        return jsonify({"error": "Firestore not initialized"}), 500
    
    try:
        # Fetch all tournaments
        tournaments_ref = db.collection('tournaments').get()
        annual_standings = {}
        processed_tournaments = []
        
        for doc in tournaments_ref:
            tournament_data = doc.to_dict()
            tournament_id = doc.id
            
            # Skip if team assignments don't participate in annual championship
            team_assignments = tournament_data.get('teams', [])
            annual_teams = [team for team in team_assignments if team.get('participatesInAnnual', True)]
            
            if not annual_teams:
                continue
            
            # Get tournament parameters
            org_id = tournament_data.get('orgId', '1')
            tourn_id = tournament_data.get('tournId')
            year = tournament_data.get('year', '2025')
            current_par = tournament_data.get('par', 71)
            
            if not tourn_id:
                continue
            
            # Fetch leaderboard data
            params = {'orgId': org_id, 'tournId': tourn_id, 'year': year}
            leaderboard_data, error = make_rapidapi_request('/leaderboard', params)
            
            if error or not leaderboard_data:
                app.logger.warning(f"Could not fetch leaderboard for tournament {tournament_id}: {error}")
                continue
            
            # Check if tournament is officially complete
            tournament_status = get_tournament_status_from_api(leaderboard_data)
            if not tournament_status['isOfficialComplete']:
                app.logger.info(f"Skipping incomplete tournament {tournament_id} (status: {tournament_status['status']})")
                continue
            
            # Calculate team scores for this tournament
            leaderboard_rows = leaderboard_data.get('leaderboardRows', [])
            team_scores = calculate_team_scores(leaderboard_rows, annual_teams, current_par)
            
            # Sort teams by score and assign points
            team_scores.sort(key=lambda x: x['totalScore'] if x['totalScore'] is not None else float('inf'))
            
            tournament_info = {
                'tournamentId': tournament_id,
                'name': tournament_data.get('name', 'Unknown Tournament'),
                'completedAt': tournament_status['lastUpdated'],
                'teamResults': []
            }
            
            for position, team in enumerate(team_scores, 1):
                if team['totalScore'] is not None:
                    # Award points based on position (adjust as needed)
                    points = max(0, len(team_scores) - position + 1)
                    
                    team_name = team['teamName']
                    if team_name not in annual_standings:
                        annual_standings[team_name] = {
                            'teamName': team_name,
                            'totalPoints': 0,
                            'tournaments': [],
                            'wins': 0,
                            'top3': 0
                        }
                    
                    annual_standings[team_name]['totalPoints'] += points
                    annual_standings[team_name]['tournaments'].append({
                        'tournamentId': tournament_id,
                        'name': tournament_data.get('name'),
                        'position': position,
                        'points': points,
                        'score': team['totalScore']
                    })
                    
                    if position == 1:
                        annual_standings[team_name]['wins'] += 1
                    if position <= 3:
                        annual_standings[team_name]['top3'] += 1
                    
                    tournament_info['teamResults'].append({
                        'teamName': team_name,
                        'position': position,
                        'score': team['totalScore'],
                        'points': points
                    })
            
            processed_tournaments.append(tournament_info)
        
        # Sort annual standings by total points
        final_standings = sorted(annual_standings.values(), 
                               key=lambda x: x['totalPoints'], reverse=True)
        
        return jsonify({
            'standings': final_standings,
            'tournaments': processed_tournaments,
            'metadata': {
                'calculatedAt': datetime.now().isoformat(),
                'tournamentCount': len(processed_tournaments),
                'teamCount': len(final_standings)
            }
        })
        
    except Exception as e:
        app.logger.error(f"Error calculating annual championship: {e}")
        return jsonify({"error": str(e)}), 500

# --- Stored Scores Management API ---
@app.route('/api/tournaments/<tournament_id>/stored_scores', methods=['GET'])
def get_tournament_stored_scores(tournament_id):
    """Get stored team scores for a tournament"""
    if not db:
        return jsonify({"error": "Firestore not initialized"}), 500
    
    try:
        stored_results = get_stored_scores(tournament_id, max_age_minutes=60)  # Longer window for manual retrieval
        
        if stored_results:
            return jsonify({
                "hasStoredScores": True,
                "teamScores": stored_results['teamScores'],
                "metadata": stored_results.get('metadata', {}),
                "calculatedAt": stored_results.get('calculatedAt'),
                "fromStorage": True
            })
        else:
            return jsonify({
                "hasStoredScores": False,
                "message": "No recent stored scores found"
            })
            
    except Exception as e:
        app.logger.error(f"Error retrieving stored scores for tournament {tournament_id}: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/tournaments/<tournament_id>/recalculate_scores', methods=['POST'])
def force_recalculate_scores(tournament_id):
    """Force recalculation and storage of team scores"""
    if not db:
        return jsonify({"error": "Firestore not initialized"}), 500
    
    try:
        # Get tournament data
        doc_ref = db.collection('tournaments').document(tournament_id)
        doc = doc_ref.get()
        if not doc.exists:
            return jsonify({"error": "Tournament not found"}), 404
        
        tournament_data = doc.to_dict()
        org_id = tournament_data.get('orgId', '1')
        tourn_id = tournament_data.get('tournId')
        year = tournament_data.get('year', '2025')
        current_par = tournament_data.get('par', 71)
        team_assignments = tournament_data.get('teams', [])
        
        if not tourn_id:
            return jsonify({"error": "Tournament missing tournId"}), 400
        
        # Fetch fresh leaderboard data
        params = {'orgId': org_id, 'tournId': tourn_id, 'year': year}
        leaderboard_data, error = make_rapidapi_request('/leaderboard', params)
        
        if error:
            return jsonify({"error": f"Failed to fetch leaderboard: {error}"}), 500
        
        # Add tournament status
        tournament_status = get_tournament_status_from_api(leaderboard_data)
        enhanced_data = {
            **leaderboard_data,
            'tournamentStatus': tournament_status,
            'isOfficiallyComplete': tournament_status['isOfficialComplete']
        }
        
        # Calculate team scores
        leaderboard_rows = leaderboard_data.get('leaderboardRows', [])
        team_scores = calculate_team_scores(leaderboard_rows, team_assignments, current_par)
        
        calculation_metadata = {
            'par': current_par,
            'teamCount': len(team_scores),
            'playerCount': len(leaderboard_rows),
            'calculatedAt': datetime.now().isoformat(),
            'fromStorage': False,
            'forceRecalculated': True
        }
        
        # Store the results
        success = store_calculated_scores(tournament_id, enhanced_data, team_scores, calculation_metadata)
        
        if success:
            return jsonify({
                "message": "Team scores recalculated and stored successfully",
                "teamScores": team_scores,
                "metadata": calculation_metadata
            })
        else:
            return jsonify({"error": "Failed to store calculated scores"}), 500
            
    except Exception as e:
        app.logger.error(f"Error force recalculating scores for tournament {tournament_id}: {e}")
        return jsonify({"error": str(e)}), 500

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

# --- Automated Tournament Monitoring System ---
class TournamentMonitor:
    def __init__(self, app, db):
        self.app = app
        self.db = db
        self.monitoring_active = True
        
        # Tournament day schedule (45-minute intervals from 7:30 AM to 9:00 PM)
        self.tournament_schedule = [
            "07:30",  # Pre-round setup
            "08:15",  # Round start coverage
            "09:00",  # Early morning update
            "09:45",  # Mid-morning 1
            "10:30",  # Mid-morning 2
            "11:15",  # Late morning 1
            "12:00",  # Pre-lunch update
            "12:45",  # Lunch break coverage
            "13:30",  # Post-lunch restart
            "14:15",  # Early afternoon
            "15:00",  # Mid-afternoon 1
            "15:45",  # Mid-afternoon 2
            "16:30",  # Late afternoon 1
            "17:15",  # Late afternoon 2
            "18:00",  # Evening coverage begins
            "18:45",  # Late evening 1
            "19:30",  # Standard end time
            "20:15",  # Extended coverage 1
            "21:00",  # Final call (tournament overrun)
        ]  # Total: 19 scheduled calls + 1 buffer call = 20/day limit
    
    def is_tournament_day(self):
        """Check if today has active tournaments"""
        try:
            tournaments_ref = self.db.collection('tournaments')
            tournaments = tournaments_ref.stream()
            
            for tournament_doc in tournaments:
                tournament_data = tournament_doc.to_dict()
                
                # Check if tournament is active and in progress
                if self.is_tournament_currently_active(tournament_data):
                    return True
            
            return False
            
        except Exception as e:
            self.app.logger.error(f"Error checking tournament day status: {e}")
            return False
    
    def is_tournament_currently_active(self, tournament_data):
        """Determine if a tournament is currently active (not completed)"""
        # Skip if already marked as complete
        if tournament_data.get('isOfficiallyComplete', False):
            return False
        if tournament_data.get('isComplete', False):
            return False
            
        # Check if we have the required API parameters
        tourn_id = tournament_data.get('tournId')
        return bool(tourn_id)  # If we have tournament ID, consider it potentially active
    
    def should_run_scheduled_check(self):
        """Check if current time matches tournament schedule and we have active tournaments"""
        # First check if we have any tournaments that could be active
        if not self.is_tournament_day():
            return False
        
        # Check if current time matches our schedule
        current_time = datetime.now().strftime("%H:%M")
        return current_time in self.tournament_schedule
        
    def check_active_tournaments(self):
        """Check for active tournaments and update their status (only during scheduled times)"""
        # Only proceed if it's a scheduled tournament monitoring time
        if not self.should_run_scheduled_check():
            self.app.logger.debug("Skipping tournament check - not a scheduled time or no active tournaments")
            return
        
        if not self.db or not check_rate_limit():
            self.app.logger.warning("Cannot check tournaments - database or rate limit issue")
            return
            
        try:
            with self.app.app_context():
                self.app.logger.info(f"Scheduled tournament check at {datetime.now().strftime('%H:%M')}")
                
                # Get all tournaments
                tournaments_ref = self.db.collection('tournaments').get()
                active_count = 0
                
                for doc in tournaments_ref:
                    tournament_data = doc.to_dict()
                    
                    # Skip if already completed
                    if tournament_data.get('isOfficiallyComplete', False) or tournament_data.get('isComplete', False):
                        continue
                    
                    org_id = tournament_data.get('orgId', '1')
                    tourn_id = tournament_data.get('tournId')
                    year = tournament_data.get('year', '2025')
                    
                    if not tourn_id:
                        continue
                    
                    active_count += 1
                    
                    # Check tournament status using RapidAPI
                    params = {'orgId': org_id, 'tournId': tourn_id, 'year': year}
                    leaderboard_data, error = make_rapidapi_request('/leaderboard', params)
                    
                    if error or not leaderboard_data:
                        self.app.logger.warning(f"Failed to get data for tournament {doc.id}: {error}")
                        continue
                    
                    # Get tournament status
                    tournament_status = get_tournament_status_from_api(leaderboard_data)
                    
                    # Check if scores need recalculation
                    if should_recalculate_scores(doc.id, leaderboard_data):
                        self.app.logger.info(f"Recalculating scores for tournament {doc.id} during scheduled check")
                        
                        # Calculate team scores
                        team_scores = calculate_team_scores(leaderboard_data, tournament_data)
                        
                        # Store calculated scores
                        metadata = {
                            'calculationReason': 'scheduled_tournament_update',
                            'tournamentStatus': tournament_status,
                            'updateTime': datetime.now().isoformat(),
                            'scheduledTime': datetime.now().strftime('%H:%M')
                        }
                        
                        store_calculated_scores(doc.id, leaderboard_data, team_scores, metadata)
                    
                    # Update tournament status in database if needed
                    updates = {}
                    if tournament_status['isOfficialComplete']:
                        updates['isOfficiallyComplete'] = True
                        updates['isComplete'] = True
                        updates['completedAt'] = firestore.SERVER_TIMESTAMP
                        updates['finalStatus'] = tournament_status['status']
                        self.app.logger.info(f"Tournament {doc.id} marked as officially complete")
                        
                    if tournament_status['isInProgress'] and not tournament_status['isOfficialComplete']:
                        updates['isActive'] = True
                        updates['lastStatusCheck'] = firestore.SERVER_TIMESTAMP
                        
                    if updates:
                        doc.reference.update(updates)
                        self.app.logger.info(f"Updated tournament {doc.id} status: {tournament_status['status']}")
                
                self.app.logger.info(f"Scheduled check complete - processed {active_count} active tournaments")
                        
        except Exception as e:
            self.app.logger.error(f"Error in tournament monitoring: {e}")

def start_tournament_monitoring():
    """Start the automated tournament monitoring system with tournament-day scheduling"""
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    import atexit
    
    if not db:
        app.logger.warning("Database not initialized, skipping tournament monitoring")
        return
    
    monitor = TournamentMonitor(app, db)
    scheduler = BackgroundScheduler()
    
    # Schedule monitoring at each specific tournament time (19 times per day)
    tournament_times = [
        "07:30", "08:15", "09:00", "09:45", "10:30", "11:15",
        "12:00", "12:45", "13:30", "14:15", "15:00", "15:45", 
        "16:30", "17:15", "18:00", "18:45", "19:30", "20:15", "21:00"
    ]
    
    for time_str in tournament_times:
        hour, minute = time_str.split(':')
        
        scheduler.add_job(
            func=monitor.check_active_tournaments,
            trigger=CronTrigger(hour=int(hour), minute=int(minute)),
            id=f'tournament_monitor_{time_str}',
            name=f'Tournament check at {time_str}',
            replace_existing=True
        )
    
    scheduler.start()
    app.logger.info(f"Tournament monitoring system started - {len(tournament_times)} daily checks during tournament hours")
    app.logger.info("Schedule: 07:30-21:00 (45-minute intervals) = 19 calls/day + 1 buffer")
    
    # Shut down the scheduler when exiting the app
    atexit.register(lambda: scheduler.shutdown())

# Initialize database optimizer
if db:
    db_optimizer = FirestoreOptimizer(db)
else:
    db_optimizer = None

# Start tournament monitoring
start_tournament_monitoring()

# --- Flask App Run ---
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
