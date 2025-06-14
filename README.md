# Alumni Golf Tournament Leaderboard Backend

This repository contains the backend API for the Alumni Golf Tournament Leaderboard platform. It provides RESTful endpoints for managing tournaments, teams, golfers, and live scoring data, enabling the frontend to display real-time leaderboards and manage tournament logistics.

## Features

- **REST API** for tournament, team, and player management
- **Live leaderboard data** integration with external golf data providers
- **Draft and team assignment endpoints**
- **Score calculation logic** (best 3-of-4 golfer scores per team per round)
- **Manual odds and draft board support**
- **CORS support** for seamless frontend integration

## Endpoints Overview

> _Note: All endpoints are prefixed with `/api`_

- `GET /api/tournaments`  
  List all tournaments

- `GET /api/tournaments/<tournament_id>`  
  Get details for a specific tournament

- `POST /api/tournaments`  
  Create a new tournament

- `PUT /api/tournaments/<tournament_id>/teams`  
  Update team assignments for a tournament

- `GET /api/leaderboard`  
  Fetch live leaderboard data (requires query params: `tournId`, `orgId`, `year`)

- `GET /api/player_odds`  
  Get player odds for drafting (requires query param: `oddsId`)

- _More endpoints may be available for managing golfers, odds, and drafts as needed._

## How It Works

- On tournament creation, teams and golfer assignments are stored in the backend.
- The backend fetches or receives live golf data (scores, cuts, etc) from external APIs or providers.
- Endpoints expose this data to the frontend, which transforms and displays it for users.

## Getting Started

1. **Clone the repository:**
    ```bash
    git clone https://github.com/socrbot/leaderboard-backend.git
    cd leaderboard-backend
    ```

2. **Set up your environment:**
    - Requires Python 3.8+
    - Recommended to use a virtual environment

    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3. **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4. **Configure environment variables:**
    - Copy `.env.example` to `.env` and fill in any required API keys or configuration.

5. **Run the server:**
    ```bash
    flask run
    ```
    The API will be available at `http://localhost:5000/api`.

## Deployment

- The backend can be deployed to any service that supports Python/Flask (e.g., Google Cloud Run, Heroku, AWS).
- For production, set appropriate environment variables and configure CORS as needed.

## Project Structure
leaderboard-backend/
├── app.py # Main Flask application
├── routes/ # Route blueprints (tournaments, leaderboard, teams, etc)
├── models/ # Data models and persistence logic
├── services/ # External API integrations and business logic
├── requirements.txt # Python dependencies
├── .env.example # Example environment config
└── …

## Customization

- **Add new endpoints:** Create new route files in `routes/` and register them in `app.py`.
- **Change scoring logic:** Update relevant service or model files.
- **Integrate new data providers:** Add new service modules and wire up as needed.

## Contributing

Pull requests and issues are welcome! Please open an issue to discuss any significant changes.

## License

