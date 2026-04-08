# Golf Leaderboard Backend API

Flask backend API for golf tournament leaderboard management with RapidAPI integration, automated tournament monitoring, and annual championship tracking.

## Features

- **Live Tournament Data**: Integration with RapidAPI for real-time leaderboard updates
- **Team Score Calculation**: Automatic calculation using best 3 of 4 golfers per round
- **Annual Championship**: Aggregate tournament results with position-based points system
- **Rate Limiting**: Intelligent API usage tracking and optimization
- **Caching**: Multi-layer caching for performance optimization

## Annual Championship Scoring

The backend calculates annual championship standings by aggregating results from all completed tournaments.

### Team Scoring Algorithm (`calculate_team_scores`)

**Per Round Calculation:**
1. Collect all 4 golfers' scores for each round
2. Sort scores (lowest to highest)
3. Take the **best 3 scores** as the team's round score
4. If a golfer is cut:
   - Calculate penalty: `highest_non_cut_score + 1`
   - Use penalty score in place of actual score

**Tournament Total:**
- Sum of all round scores
- Only counts if team has at least 3 valid scores per round

### Championship Points System

**Points Award Formula:**
```python
points = max(0, team_count - position + 1)
```

**Example** (8 teams competing):
- 1st place: 8 points
- 2nd place: 7 points
- 3rd place: 6 points
- ...
- 8th place: 1 point

**Eligibility Requirements:**
- Tournament must be **officially complete** (final round finished)
- Team must have `participatesInAnnual: true` in tournament data
- Team must have a valid total score

### API Endpoint

**GET** `/api/annual_championship`

Returns standings with:
- `totalPoints`: Sum of points from all completed tournaments
- `tournaments`: Array of tournament results with position, score, and points
- Sorted by total points (highest first)

## Deployment

### Production
- **URL**: `https://leaderboard-backend-628169335141.us-east1.run.app/api`
- Deployed via GitHub Actions workflow on merge to `main`

### Staging
- **URL**: `https://leaderboard-backend-staging-1056126670188.us-east1.run.app/api`
- Manual deployment or PR testing

## Documentation

See [API_DOCUMENTATION.md](API_DOCUMENTATION.md) for complete endpoint reference.
