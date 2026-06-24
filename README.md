# Golf Leaderboard Backend API

A Flask REST API that powers the Sunday Cup alumni golf tournament platform. It integrates with RapidAPI for live PGA Tour leaderboard data, calculates team scores using a best-3-of-4 algorithm, manages multi-league membership, and tracks cumulative annual championship standings across a full season.

## Features

- **Live Tournament Data** — RapidAPI proxy with circuit breaker, rate limiting (20 calls/day, 200/month), and configurable polling interval
- **Team Score Calculation** — Best-3-of-4 golfer scoring per round; CUT penalty = highest non-cut score + 1
- **Stored Score Snapshots** — Completed tournament scores persisted to Firestore for instant reads without API calls
- **Multi-League Architecture** — Users create or join leagues via invite code; tournaments are scoped to a league
- **Snake Draft System** — Draft lock/pick/complete flow with per-pick validation and FCM push notifications
- **Player Odds Integration** — SportsData.io odds seeded at tournament creation; weekly auto-refresh before lock-in
- **Annual Championship** — Cumulative stroke standings across all completed `participatesInAnnual` tournaments
- **Rate Limiting** — Flask-Limiter guards on mutating endpoints; RapidAPI quota tracked in Firestore
- **Caching** — Flask-Caching with configurable TTLs (`TOURNAMENT_CACHE_TTL=10min`, `LEADERBOARD_CACHE_TTL=3min`)

## Prerequisites

- Python 3.11+
- A Firebase project with Firestore and Authentication enabled
- A Firebase service account key (JSON)
- RapidAPI key for [Live Golf Data](https://rapidapi.com/nuvem/api/live-golf-data)
- SportsData.io API key (for player odds)

## Installation

```bash
# Clone the repository
git clone https://github.com/socrbot/leaderboard-backend.git
cd leaderboard-backend

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

Copy the environment template and fill in your credentials:

```bash
cp .env.template .env
```

```env
RAPIDAPI_KEY=your_rapidapi_key
SPORTSDATA_IO_API_KEY=your_sportsdata_key
FIREBASE_SERVICE_ACCOUNT_KEY_PATH=/path/to/serviceAccountKey.json
```

## Usage

### Development

```bash
flask run --port 8080
# or
gunicorn app:app --bind 0.0.0.0:8080
```

The API is available at `http://localhost:8080/api`.

### Key Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/tournaments?year=2026` | List tournaments (auth optional) |
| `GET` | `/api/tournaments/<id>/leaderboard` | Live or stored team scores |
| `GET` | `/api/tournaments/<id>/draft_status` | Draft lock/start/complete state |
| `POST` | `/api/leagues` | Create a league |
| `POST` | `/api/leagues/join` | Join league by invite code |
| `GET` | `/api/annual_championship?year=2026` | Season cumulative standings |
| `GET` | `/api/rate_limit_status` | RapidAPI quota usage |

See [API_DOCUMENTATION.md](API_DOCUMENTATION.md) for the full reference.

### Team Score Algorithm

```
For each round:
  1. Collect all 4 golfer scores
  2. CUT players → penalty = max(non_cut_scores) + 1
  3. Sort scores ascending, take best 3
  4. Team round score = sum of best 3
Tournament total = sum of round scores
```

### Annual Championship

```
annual_total = Σ tournament_scores   (lower is better)
Eligibility: isOfficiallyComplete=true AND participatesInAnnual=true
```

## Deployment

Deployment is fully automated via GitHub Actions. **Do not run `gcloud` commands manually.**

| Branch | Service | URL |
|---|---|---|
| `main` | `leaderboard-backend` | `https://leaderboard-backend-628169335141.us-east1.run.app/api` |
| `v2-prod` | `leaderboard-backend-v2` | V2 production |
| `staging` | `leaderboard-backend-staging-...` | `https://leaderboard-backend-staging-1056126670188.us-east1.run.app/api` |

Both Cloud Run services are deployed to `us-east1` in project `alumni-golf-tournament`.

## Contributing

1. Fork the repository and create a feature branch from `staging`.
2. Test against the staging backend before targeting `main` or `v2-prod`.
3. The `main` branch is protected — open a pull request; direct pushes are rejected.
4. Ensure new endpoints follow the existing auth decorator pattern:
   - Public read → no decorator
   - Authenticated read → `@require_auth`
   - League admin write → `@require_league_admin`

## License

MIT License. See [LICENSE](LICENSE) for details.
