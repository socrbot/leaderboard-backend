# backend/app.py
import os
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
import time # Import time module

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
CORS(app) # Enable CORS for all routes by default

# RapidAPI credentials from environment variables
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
RAPIDAPI_HOST = "live-golf-data.p.rapidapi.com"
API_ENDPOINT = "https://live-golf-data.p.rapidapi.com/leaderboard" # Base endpoint, params added later

if not RAPIDAPI_KEY:
    print("Error: RAPIDAPI_KEY environment variable not set.")
    RAPIDAPI_KEY = "dummy_key_if_not_set" # Provide a dummy for dev if not set

# --- Cache variables ---
CACHE = {}
CACHE_TTL_SECONDS = 60 * 60 # Cache data for 5 minutes (adjust as needed, e.g., 60 for 1 min, 300 for 5 min)

@app.route('/api/leaderboard', methods=['GET'])
def get_leaderboard():
    # Construct a unique cache key based on request parameters
    cache_key_params = request.args.to_dict()
    cache_key = tuple(sorted(cache_key_params.items())) # Use sorted tuple for consistent key

    # Check cache first
    if cache_key in CACHE:
        cached_data, timestamp = CACHE[cache_key]
        if (time.time() - timestamp) < CACHE_TTL_SECONDS:
            app.logger.info("Returning cached data for leaderboard.")
            return jsonify(cached_data)

    # If not in cache or expired, fetch from RapidAPI
    app.logger.info("Fetching fresh data from RapidAPI.")
    # Use request.args.get with defaults or pass from frontend if desired
    org_id = request.args.get('orgId', '1')
    tourn_id = request.args.get('tournId', '033')
    year = request.args.get('year', '2025') # Ensure this is '2024' as it worked in Postman

    rapidapi_url = f"{API_ENDPOINT}?orgId={org_id}&tournId={tourn_id}&year={year}"

    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": RAPIDAPI_HOST
    }

    print(f"DEBUG: Calling RapidAPI URL: {rapidapi_url}")
    print(f"DEBUG: With headers (partial): X-RapidAPI-Key: {RAPIDAPI_KEY[:5]}... Host: {RAPIDAPI_HOST}")

    try:
        response = requests.get(rapidapi_url, headers=headers)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        data = response.json()
        print(f"DEBUG: RapidAPI Call Successful. Status: {response.status_code}")

        # Cache the new data
        CACHE[cache_key] = (data, time.time())
        return jsonify(data)
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error fetching data from RapidAPI: {e}")
        if e.response is not None:
            app.logger.error(f"RapidAPI Response Status Code: {e.response.status_code}")
            app.logger.error(f"RapidAPI Response Content: {e.response.text}")
        return jsonify({"error": "Failed to fetch data from external API", "details": str(e)}), 500
    except ValueError:
        app.logger.error("Failed to parse JSON response from RapidAPI")
        return jsonify({"error": "Invalid JSON response from external API"}), 500

# if __name__ == '__main__':
#    # Get the port from the environment variable or default to 8080
#    port = int(os.environ.get("PORT", 8080))
#    app.run(host="0.0.0.0", port=port, debug=False) # Set debug to False for production