# Golf Leaderboard Backend API Documentation

## Overview
Optimized backend for golf tournament leaderboard management with RapidAPI integration, automated tournament monitoring, and intelligent rate limiting.

## Base URL
- Production: `https://leaderboard-backend-628169335141.us-east1.run.app/api`
- Local Development: `http://localhost:8080/api`

## API Endpoints

### Rate Limiting & Status

#### GET /rate_limit_status
Get current API rate limit status and usage statistics.

**Response:**
```json
{
  "daily_calls": 5,
  "monthly_calls": 45,
  "daily_limit": 20,
  "monthly_limit": 200,
  "can_make_call": true
}
```

### Tournament Schedule

#### GET /schedule
Get PGA Tour schedule using RapidAPI.

**Parameters:**
- `year` (string): Tournament year (default: "2025")
- `orgId` (string): Organization ID (default: "1" for PGA Tour)

**Example:** `/schedule?year=2025&orgId=1`

### Tournament Information

#### GET /tournament_info
Get detailed tournament information using RapidAPI.

**Parameters:**
- `orgId` (string): Organization ID (default: "1")
- `tournId` (string, required): Tournament ID
- `year` (string): Tournament year (default: "2025")

**Example:** `/tournament_info?tournId=033&year=2025`

### Leaderboard Data

#### GET /leaderboard
Get optimized leaderboard with optional team score calculations.

**Parameters:**
- `orgId` (string): Organization ID (default: "1")
- `tournId` (string): Tournament ID (default: "033")
- `year` (string): Tournament year (default: "2025")
- `roundId` (string, optional): Specific round ID
- `calculateTeams` (boolean): Calculate team scores (default: false)
- `tournamentId` (string): Firestore tournament ID for team calculations

**Response includes:**
- Standard RapidAPI leaderboard data
- Tournament status information
- Team scores (if requested)
- Official completion status

**Example:** `/leaderboard?tournId=033&year=2025&calculateTeams=true&tournamentId=doc_id`

### Annual Championship

#### GET /annual_championship
Calculate annual championship standings from all completed tournaments.

**Response:**
```json
{
  "standings": [
    {
      "teamName": "Team Alpha",
      "totalPoints": 85,
      "tournaments": [...],
      "wins": 2,
      "top3": 4
    }
  ],
  "tournaments": [...],
  "metadata": {
    "calculatedAt": "2025-07-18T10:30:00Z",
    "tournamentCount": 5,
    "teamCount": 8
  }
}
```

### Player Odds

#### GET /player_odds
Get player betting odds with draft lock functionality.

**Parameters:**
- `oddsId` (string, required): SportsData.io odds ID

**Features:**
- Returns locked odds if draft has started
- Falls back to live odds if draft not started
- Calculates average odds across multiple sportsbooks

### Stored Scores Management

#### GET /tournaments/{tournament_id}/stored_scores
Get stored/cached team scores for a tournament.

**Response:**
```json
{
  "hasStoredScores": true,
  "teamScores": [...],
  "metadata": {
    "par": 71,
    "calculatedAt": "2025-07-18T15:30:00Z",
    "fromStorage": true
  },
  "calculatedAt": "2025-07-18T15:30:00Z"
}
```

#### POST /tournaments/{tournament_id}/recalculate_scores
Force recalculation and storage of team scores (bypasses cache).

**Response:**
```json
{
  "message": "Team scores recalculated and stored successfully",
  "teamScores": [...],
  "metadata": {
    "forceRecalculated": true,
    "calculatedAt": "2025-07-18T15:30:00Z"
  }
}
```

### Tournament Management

#### POST /tournaments
Create a new tournament.

**Request Body:**
```json
{
  "name": "Tournament Name",
  "orgId": "1",
  "tournId": "033",
  "year": "2025",
  "oddsId": "12345"
}
```

#### GET /tournaments
Get all tournaments.

#### GET /tournaments/{tournament_id}
Get single tournament with live status updates.

#### PUT /tournaments/{tournament_id}/teams
Update tournament teams.

#### POST /tournaments/{tournament_id}/start_draft
Start draft and lock in current odds.

### Global Teams Management

#### GET /global_teams
Get all global teams.

#### POST /global_teams
Create a new global team.

#### PUT /global_teams/{team_id}
Update a global team.

#### DELETE /global_teams/{team_id}
Delete a global team.

### Tournament Team Assignments

#### GET /tournaments/{tournament_id}/team_assignments
Get team assignments for a tournament.

#### PUT /tournaments/{tournament_id}/team_assignments
Update team assignments for a tournament.

## Features

### Rate Limiting
- **Daily Limit:** 20 API calls
- **Monthly Limit:** 200 API calls
- **Optimal Distribution:** 45-minute intervals between calls
- **Coverage Window:** 7:30 AM - 9:00 PM (13.5 hours)

### Tournament Status Detection
- Automatic detection of tournament completion using "Official" status
- Real-time status monitoring and updates
- Background job scheduling for continuous monitoring

### Team Score Calculations
- Best 3 of 4 players per round
- **Cut player penalty system:** Cut players receive the score of the highest remaining (non-cut) golfer + 1 stroke for rounds they didn't complete
- Support for MongoDB $numberInt objects
- Comprehensive error handling

### Caching Strategy
- **General Data:** 5 minutes
- **Tournament Data:** 10 minutes  
- **Live Leaderboard:** 3 minutes
- Redis support for production environments

### Error Handling
- Comprehensive error logging
- Graceful degradation for API failures
- Rate limit protection with informative error messages
- Firebase connection resilience

## Environment Variables

Required environment variables:
```bash
RAPIDAPI_KEY=your_rapidapi_key
SPORTSDATA_IO_API_KEY=your_sportsdata_key
FIREBASE_SERVICE_ACCOUNT_KEY_PATH=path/to/service_account.json
MAX_DAILY_CALLS=20
MAX_MONTHLY_CALLS=200
```

## Deployment

### Google Cloud Run
```bash
# Set environment variables
export RAPIDAPI_KEY=your_key
export SPORTSDATA_IO_API_KEY=your_key

# Deploy
./deploy.sh
```

### Local Development
```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export RAPIDAPI_KEY=your_key
export SPORTSDATA_IO_API_KEY=your_key

# Run
python app.py
```

## Monitoring

### Health Checks
- Rate limit status endpoint
- Tournament monitoring system
- API response validation

### Logging
- Structured logging with timestamps
- Error tracking and alerting
- API usage monitoring

### Performance Metrics
- Response times
- Cache hit rates
- API call distribution
- Tournament processing times

## Rate Limit Optimization

### Daily Distribution (20 calls)
- **Interval:** 45 minutes between calls
- **Coverage:** 13.5 hours (7:30 AM - 9:00 PM)
- **Buffer:** 30-minute window for urgent requests

### Monthly Planning (200 calls)
- **Average:** 6.45 calls per day
- **Peak Days:** Tournament weekends (higher frequency)
- **Off Days:** Reduced monitoring for completed tournaments

## Security

### API Key Management
- Environment variable storage
- No hardcoded credentials
- Secure Cloud Run deployment

### CORS Configuration
- Configured for frontend domain
- Secure headers with Helmet
- Request validation and sanitization

## Future Enhancements

### Planned Features
1. **Redis Caching:** Production-grade caching layer
2. **WebSocket Updates:** Real-time tournament updates
3. **Advanced Analytics:** Player performance metrics
4. **Multi-tournament Support:** Concurrent tournament monitoring
5. **Mobile API:** Optimized endpoints for mobile apps

### Performance Improvements
1. **Database Optimization:** Firestore query optimization
2. **CDN Integration:** Static asset caching
3. **Load Balancing:** Multi-region deployment
4. **Background Processing:** Async tournament calculations
