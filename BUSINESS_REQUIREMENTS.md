# Golf Leaderboard Backend API - Business Requirements Document

**Version**: 1.0  
**Last Updated**: April 11, 2026  
**Document Owner**: Backend Engineering Team  
**Project**: Alumni Golf Tournament Leaderboard System - API Service

---

## 1. Executive Summary

### 1.1 Purpose
The Golf Leaderboard Backend is a Flask-based RESTful API service that provides golf tournament data aggregation, team score calculations, and tournament management functionality. The system integrates with third-party golf data providers (RapidAPI, SportsData.io) and manages tournament state in Firebase/Firestore.

### 1.2 Business Objectives
- Provide real-time golf tournament leaderboard data with < 1 second response time
- Accurately calculate team scores using best-3-of-4 player scoring
- Manage annual championship standings across multiple tournaments
- Optimize external API usage to stay within rate limits (20 calls/day)
- Support complete tournament lifecycle from creation to completion
- Enable seamless draft management workflow
- Maintain 99.5% uptime during tournament season

### 1.3 Success Metrics
- API response time: < 500ms for cached requests, < 2s for fresh data
- Data accuracy: 100% match with authoritative sources (RapidAPI)
- API availability: 99.5% uptime (target: 99.9%)
- Rate limit compliance: < 20 RapidAPI calls per day
- Cache hit ratio: > 80% for leaderboard requests
- Database operation success rate: > 99.9%

---

## 2. Stakeholders

### 2.1 Primary Stakeholders
- **Frontend Application**: Primary API consumer
- **Tournament Administrators**: Users managing tournaments via API
- **System Operators**: DevOps monitoring and maintaining service
- **End Users**: Indirectly through frontend application

### 2.2 External Dependencies
- **RapidAPI (Live Golf Data)**: Source of truth for tournament scores
- **SportsData.io**: Player betting odds provider
- **Firebase/Firestore**: Database and authentication platform
- **Google Cloud Run**: Hosting platform

---

## 3. Functional Requirements

### 3.1 Tournament Data Integration

#### 3.1.1 RapidAPI Integration
**Requirement ID**: FR-API-001  
**Priority**: Critical  
**Description**: Integrate with RapidAPI Live Golf Data service for tournament information

**Acceptance Criteria**:
- Fetch tournament schedules by year and organization
- Retrieve tournament leaderboards with player scores
- Get detailed tournament information (course, par, dates)
- Handle rate limiting (20 calls/day maximum)
- Implement 5-minute cache for all requests
- Track API usage and remaining quota
- Parse MongoDB-style field wrappers (`$numberInt`, `$date`)

**API Endpoints Required**:
- `/schedule` - PGA Tour schedule
- `/leaderboard` - Tournament leaderboard
- `/tournament_info` - Tournament details

#### 3.1.2 SportsData.io Integration
**Requirement ID**: FR-API-002  
**Priority**: High  
**Description**: Integrate with SportsData.io for player betting odds

**Acceptance Criteria**:
- Fetch player odds by tournament
- Calculate average odds across multiple sportsbooks
- Support odds locking for draft purposes
- Cache odds data to minimize API calls
- Handle missing or incomplete odds data gracefully

### 3.2 Tournament Management

#### 3.2.1 Tournament CRUD Operations
**Requirement ID**: FR-TM-001  
**Priority**: Critical  
**Description**: Provide complete tournament lifecycle management

**Acceptance Criteria**:

**Create Tournament** (`POST /api/tournaments`):
- Required fields: name, orgId, tournId, year
- Optional fields: oddsId, par, course, dates
- Auto-generate unique document ID
- Initialize empty teams array
- Set default values: `participatesInAnnual: false`, `IsDraftComplete: false`

**Read Tournament** (`GET /api/tournaments/{id}`):
- Return tournament metadata
- Include real-time status from RapidAPI
- Calculate and include draft status flags
- Enrich with team data if available

**Update Tournament** (`PUT /api/tournaments/{id}/teams`):
- Update team assignments
- Validate team data structure
- Preserve existing draft status
- Trigger score recalculation if needed

**List Tournaments** (`GET /api/tournaments`):
- Support filtering by year
- Include status for all tournaments
- Sort by date (most recent first)
- Batch status checks for efficiency

#### 3.2.2 Tournament Status Tracking
**Requirement ID**: FR-TM-002  
**Priority**: Critical  
**Description**: Track tournament lifecycle state accurately

**Tournament States**:
1. **Created**: Tournament saved, not started
2. **Upcoming**: In schedule, not yet started
3. **In Progress**: Currently active
4. **Complete (Not Official)**: Final round finished, awaiting official results
5. **Complete (Official)**: Marked as officially complete

**Status Fields**:
- `IsTournamentLive`: Currently in progress (boolean)
- `IsTournamentComplete`: All rounds finished (boolean)
- `IsTournamentOfficial`: Marked complete by admin (boolean)
- `currentRound`: Current round number (1-4)
- `roundState`: Current round state (official, complete, in_progress)

**Acceptance Criteria**:
- Automatically determine status from RapidAPI data
- Update status on each leaderboard request
- Persist `IsTournamentOfficial` flag in database
- Provide status in all tournament responses

### 3.3 Team Score Calculation

#### 3.3.1 Best 3-of-4 Scoring Algorithm
**Requirement ID**: FR-SC-001  
**Priority**: Critical  
**Description**: Calculate team scores using best 3 individual scores per round

**Algorithm**:
```
For each round (1-4):
  1. Collect all 4 team members' scores to par
  2. Sort scores (lowest to highest)
  3. Sum the best (lowest) 3 scores
  4. If < 3 valid scores available, round score = null
  5. Team total = sum of all round scores
```

**Acceptance Criteria**:
- Use score-to-par values from RapidAPI (not strokes)
- Handle live scores (in-progress rounds)
- Correctly parse score formats: "-5", "E", "+3"
- Return null for incomplete rounds (< 3 players with scores)
- Support both completed and in-progress tournaments
- Calculate cumulative team total across all rounds

#### 3.3.2 Cut Player Penalty Calculation
**Requirement ID**: FR-SC-002  
**Priority**: High  
**Description**: Apply appropriate penalties for players who miss the cut

**Business Rules**:
- Cut typically occurs after Round 2 (R2)
- Cut players do NOT play R3 and R4
- Penalty calculation:
  - **R3 Penalty**: Worst R3 score among non-cut players + 1 stroke
  - **R4 Penalty**: Worst R4 score among non-cut players + 1 stroke
- Penalties only applied AFTER respective rounds complete
- If round not complete, penalty = null (not applied)

**Acceptance Criteria**:
- Detect cut status from player data (`status: 'cut'`)
- Calculate worst score per round dynamically
- Only consider non-cut players for worst score calculation
- Verify round completion before applying penalty (check for non-live scores)
- Use actual player scores for R1 and R2
- Apply round-specific penalties for R3 and R4
- Include penalty information in team score response

#### 3.3.3 Score-to-Par Handling
**Requirement ID**: FR-SC-003  
**Priority**: Critical  
**Description**: Use authoritative score-to-par data from RapidAPI

**Acceptance Criteria**:
- Prefer `scoreToPar` field from RapidAPI rounds array
- Fallback to calculation (strokes - par) if scoreToPar unavailable
- Parse score formats correctly:
  - "E" → 0
  - "-5" → -5
  - "+3" → +3
- Handle live scores from `currentRoundScore` field
- Verify scores match RapidAPI source (validation)

### 3.4 Annual Championship

#### 3.4.1 Championship Standings Calculation
**Requirement ID**: FR-AC-001  
**Priority**: High  
**Description**: Calculate season-long championship standings using cumulative stroke scoring

**Scoring System**:
- **Cumulative Stroke Play**: Sum of all tournament scores
- **Lower total wins** (standard golf scoring)
- Only include completed tournaments with `participatesInAnnual: true`

**Example**:
```
Team A: +5 (Tournament 1) + +8 (Tournament 2) + +3 (Tournament 3) = +16 total
Team B: +10 + +2 + +6 = +18 total
Winner: Team A (lowest total score)
```

**Acceptance Criteria**:
- Filter tournaments by `participatesInAnnual: true` flag
- Only include officially complete tournaments (`IsTournamentOfficial: true`)
- Calculate total as sum of all tournament scores
- Provide tournament-by-tournament breakdown for each team
- Sort standings by total score (lowest first)
- Handle teams that didn't participate in all tournaments
- Calculate additional statistics: wins, top-3 finishes, average finish position

#### 3.4.2 Annual Championship API
**Requirement ID**: FR-AC-002  
**Priority**: High  
**Description**: Provide API endpoint for championship standings

**Endpoint**: `GET /api/annual_championship?year={year}`

**Response Structure**:
```json
{
  "standings": [
    {
      "teamName": "Team Alpha",
      "totalScore": 16,
      "tournaments": [
        {"tournamentName": "Masters", "position": 2, "score": 5},
        {"tournamentName": "PGA Championship", "position": 1, "score": 8}
      ],
      "wins": 1,
      "top3": 2,
      "averagePosition": 1.5
    }
  ],
  "tournaments": [...],
  "metadata": {
    "year": "2026",
    "tournamentCount": 5,
    "teamCount": 8,
    "calculatedAt": "2026-04-11T10:30:00Z"
  }
}
```

### 3.5 Draft Management

#### 3.5.1 Draft Lifecycle Management
**Requirement ID**: FR-DM-001  
**Priority**: High  
**Description**: Support complete draft workflow from initialization to completion

**Draft States**:
1. **Not Started**: `IsDraftStarted: false`
2. **Started, Odds Unlocked**: `IsDraftStarted: true`, `oddsLocked: false`
3. **Started, Odds Locked**: `IsDraftStarted: true`, `oddsLocked: true`
4. **Complete**: `IsDraftComplete: true`

**State Transitions**:
- `POST /api/tournaments/{id}/start_draft_flag` → Sets `IsDraftStarted: true`
- `POST /api/tournaments/{id}/lock_draft_odds` → Locks odds, retrieves and stores player odds
- `POST /api/tournaments/{id}/complete_draft` → Sets `IsDraftComplete: true`

**Acceptance Criteria**:
- Validate state transitions (cannot skip states)
- Lock player odds when `lock_draft_odds` is called
- Store locked odds in tournament document
- Retrieve locked odds for `player_odds` endpoint when draft started
- Prevent odds changes after locking
- Return draft status via `GET /api/tournaments/{id}/draft_status`

#### 3.5.2 Player Odds Management
**Requirement ID**: FR-DM-002  
**Priority**: High  
**Description**: Manage player odds for draft purposes

**Acceptance Criteria**:
- Fetch live odds from SportsData.io
- Calculate average odds across sportsbooks
- Support odds locking at draft start
- Return locked odds if draft has started
- Return live odds if draft not started
- Cache odds data (5-minute TTL)
- Handle missing sportsbook data gracefully

### 3.6 Global Team Management

#### 3.6.1 Global Team CRUD
**Requirement ID**: FR-GT-001  
**Priority**: High  
**Description**: Manage teams that persist across multiple tournaments

**Operations**:
- **Create**: `POST /api/global_teams`
- **Read**: `GET /api/global_teams?year={year}`
- **Update**: `PUT /api/global_teams/{id}`
- **Delete**: `DELETE /api/global_teams/{id}`

**Team Structure**:
```json
{
  "teamName": "Alpha Squad",
  "year": "2026",
  "createdAt": "2026-01-15T10:00:00Z",
  "preferredGolfers": {
    "tournamentId": ["Player 1", "Player 2", "Player 3", "Player 4"]
  }
}
```

**Acceptance Criteria**:
- Validate team name uniqueness within year
- Support year-based filtering
- Store preferred golfer assignments per tournament
- Enable team reuse across multiple tournaments in same year
- Support team deletion with confirmation

#### 3.6.2 Year-Based Team Migration
**Requirement ID**: FR-GT-002  
**Priority**: Medium  
**Description**: Copy teams from one year to the next

**Endpoint**: `POST /api/global_teams/copy_year`

**Acceptance Criteria**:
- Copy all teams from source year
- Update year field to target year
- Reset preferredGolfers (tournament-specific)
- Preserve team names
- Validate source year exists
- Prevent duplicates in target year

### 3.7 Tournament Team Assignments

#### 3.7.1 Team Assignment Management
**Requirement ID**: FR-TA-001  
**Priority**: Critical  
**Description**: Assign global teams to specific tournaments with golfer selections

**Endpoints**:
- `GET /api/tournaments/{id}/team_assignments` - Get current assignments
- `PUT /api/tournaments/{id}/team_assignments` - Update assignments

**Assignment Structure**:
```json
{
  "teamId": "global_team_doc_id",
  "teamName": "Alpha Squad",
  "golferNames": ["Sam Burns", "Rory McIlroy", "Scottie Scheffler", "Viktor Hovland"]
}
```

**Acceptance Criteria**:
- Link to global team via teamId
- Require exactly 4 golfer names per team
- Validate golfer names against tournament roster
- Support Unicode characters in names (å, ø, ü, etc.)
- Support fuzzy name matching (handle Chris vs Christopher)
- Normalize names for comparison (NFD decomposition + explicit char map)
- Store assignments in tournament document
- Trigger score recalculation on assignment update

#### 3.7.2 Team Sync from Global
**Requirement ID**: FR-TA-002  
**Priority**: Medium  
**Description**: Synchronize tournament team assignments from global teams

**Endpoint**: `POST /api/tournaments/{id}/sync_teams`

**Acceptance Criteria**:
- Pull all teams for tournament year from global_teams
- Create assignment records for each team
- Populate golferNames from preferredGolfers if available
- Handle teams without preferred golfers (empty arrays)
- Update existing assignments without duplicating

### 3.8 Caching & Performance

#### 3.8.1 Response Caching
**Requirement ID**: FR-CP-001  
**Priority**: High  
**Description**: Implement intelligent caching to reduce external API calls

**Cache Strategy**:
- **Cache Duration**: 5 minutes (300 seconds)
- **Cache Key**: (endpoint, sorted request parameters)
- **Storage**: In-memory Python dictionary

**Cached Endpoints**:
- RapidAPI leaderboard requests
- SportsData.io player odds requests
- Tournament info requests

**Acceptance Criteria**:
- Check cache before making external API call
- Return cached data if < 5 minutes old
- Refresh cache on cache miss or expiration
- Include cache metadata in responses (cached: true/false, cachedAt timestamp)
- Bypass cache for force-refresh requests
- Clear cache on server restart

#### 3.8.2 Score Calculation Caching
**Requirement ID**: FR-CP-002  
**Priority**: High  
**Description**: Store calculated team scores in Firestore for performance

**Collection**: `tournament_scores`  
**Document ID**: `{tournamentId}`

**Document Structure**:
```json
{
  "results": [...],  // Calculated team scores
  "metadata": {
    "calculatedAt": "2026-04-11T15:30:00Z",
    "par": 72,
    "dataHash": "abc123...",
    "isOfficial": false
  }
}
```

**Recalculation Triggers**:
- Tournament data hash changes (player scores updated)
- Tournament marked as official
- Tournament par value changes
- Manual force recalculation (`POST /recalculate_scores`)

**Acceptance Criteria**:
- Store scores in Firestore after calculation
- Return stored scores if data unchanged
- Calculate hash of leaderboard data for change detection
- Provide metadata: calculation time, data freshness
- Support manual recalculation override
- Include worst round scores for cut penalty transparency

### 3.9 Rate Limiting

#### 3.9.1 External API Rate Limit Tracking
**Requirement ID**: FR-RL-001  
**Priority**: Critical  
**Description**: Track and enforce RapidAPI rate limits to prevent quota exhaustion

**Limits**:
- **Daily**: 20 requests
- **Monthly**: 200 requests (backup safety limit)

**Tracking**:
- Store call count in Firestore: `api_usage/rapidapi_stats`
- Increment counter on each API call
- Reset daily counter at midnight UTC
- Track monthly usage for analysis

**Acceptance Criteria**:
- Check rate limit before making API call
- Return error if limit exceeded
- Expose rate limit status via `/api/rate_limit_status`
- Parse rate limits from RapidAPI response headers
- Log rate limit violations
- Provide override mechanism for emergency requests

#### 3.9.2 Rate Limit Status API
**Requirement ID**: FR-RL-002  
**Priority**: High  
**Description**: Provide visibility into API usage and remaining quota

**Endpoint**: `GET /api/rate_limit_status`

**Response**:
```json
{
  "rapidapi_daily_calls": 5,
  "rapidapi_monthly_calls": 45,
  "rapidapi_daily_limit": 20,
  "rapidapi_monthly_limit": 200,
  "rapidapi_remaining": 15,
  "can_make_call": true,
  "last_reset": "2026-04-11T00:00:00Z"
}
```

---

## 4. Non-Functional Requirements

### 4.1 Performance

#### 4.1.1 Response Time
**Requirement ID**: NFR-PF-001  
**Priority**: High  
**Description**: Ensure fast API response times

**Targets**:
- Cached requests: < 200ms (p95)
- Database queries: < 500ms (p95)
- External API requests: < 2000ms (p95)
- Score calculations: < 1000ms for 12 teams (p95)

**Acceptance Criteria**:
- Measure and log response times
- Optimize database queries with indexes
- Implement connection pooling
- Use async operations where appropriate

#### 4.1.2 Scalability
**Requirement ID**: NFR-PF-002  
**Priority**: Medium  
**Description**: Support concurrent users and requests

**Targets**:
- Support 100 concurrent requests
- Handle 1000 requests per minute
- Auto-scale on Google Cloud Run (0-10 instances)

**Acceptance Criteria**:
- Stateless API design
- Thread-safe cache implementation (if multi-threaded)
- Efficient database connection management
- Support horizontal scaling

### 4.2 Reliability

#### 4.2.1 Availability
**Requirement ID**: NFR-RL-001  
**Priority**: Critical  
**Description**: Maintain high availability during tournament season

**Targets**:
- Uptime: 99.5% (target: 99.9%)
- Planned downtime: < 1 hour per month
- Unplanned downtime: < 30 minutes per month

**Acceptance Criteria**:
- Deploy to Cloud Run with auto-restart
- Implement health check endpoint (`/health`)
- Monitor service status
- Configure alerts for downtime
- Maintain error logs

#### 4.2.2 Error Handling
**Requirement ID**: NFR-RL-002  
**Priority**: High  
**Description**: Handle errors gracefully and provide meaningful responses

**Error Categories**:
- 400-level: Client errors (bad request, not found, validation)
- 500-level: Server errors (database, external API, internal)

**Acceptance Criteria**:
- Return appropriate HTTP status codes
- Provide error messages in JSON format
- Log all errors with context
- Include request ID for debugging
- Never expose sensitive data in errors
- Handle external API failures gracefully

### 4.3 Security

#### 4.3.1 API Key Management
**Requirement ID**: NFR-SC-001  
**Priority**: Critical  
**Description**: Securely manage external API keys and credentials

**Acceptance Criteria**:
- Store API keys in Google Cloud Secrets Manager
- Never log or expose API keys
- Rotate keys periodically (quarterly)
- Use environment variables for configuration
- Audit key usage

#### 4.3.2 CORS Configuration
**Requirement ID**: NFR-SC-002  
**Priority**: High  
**Description**: Configure CORS for secure frontend access

**Acceptance Criteria**:
- Allow specific origins (production, staging, localhost)
- Support OPTIONS requests
- Restrict to necessary HTTP methods (GET, POST, PUT, DELETE)
- Set appropriate headers (Content-Type, Authorization)

#### 4.3.3 Input Validation
**Requirement ID**: NFR-SC-003  
**Priority**: High  
**Description**: Validate all API inputs to prevent attacks

**Acceptance Criteria**:
- Validate data types
- Enforce maximum field lengths
- Sanitize string inputs
- Validate tournament IDs, years, orgIds
- Return 400 errors for invalid inputs
- Prevent SQL injection (use parameterized queries)
- Prevent NoSQL injection (validate Firestore queries)

### 4.4 Maintainability

#### 4.4.1 Code Quality
**Requirement ID**: NFR-MN-001  
**Priority**: Medium  
**Description**: Maintain clean, documented, testable code

**Standards**:
- PEP 8 Python style guide
- Function-level docstrings
- Inline comments for complex logic
- Type hints for function signatures
- Modular, single-responsibility functions

#### 4.4.2 Logging
**Requirement ID**: NFR-MN-002  
**Priority**: High  
**Description**: Implement comprehensive logging for debugging and monitoring

**Log Levels**:
- **DEBUG**: Development details
- **INFO**: Normal operations (API calls, cache hits)
- **WARNING**: Recoverable issues (rate limit approaching, fallback used)
- **ERROR**: Errors requiring attention (external API failures)
- **CRITICAL**: System failures

**Acceptance Criteria**:
- Log all API requests with method, path, params
- Log external API calls and responses
- Log cache hits/misses
- Log rate limit usage
- Include timestamps and request IDs
- Structured logging (JSON format)
- Integrate with Google Cloud Logging

### 4.5 Compatibility

#### 4.5.1 RapidAPI Data Format
**Requirement ID**: NFR-CP-001  
**Priority**: Critical  
**Description**: Support RapidAPI's data format including MongoDB field wrappers

**Data Structures**:
- `{"$numberInt": "123"}` → Parse as integer
- `{"$date": "2026-04-11T..."}` → Parse as datetime
- Nested objects and arrays

**Acceptance Criteria**:
- Parse all MongoDB-style wrappers
- Handle missing optional fields
- Support schema changes gracefully
- Validate data structure before processing

---

## 5. API Design & Documentation

### 5.1 RESTful Principles

#### 5.1.1 URL Structure
**Standard**: `/api/{resource}/{id}/{sub-resource}`

**Examples**:
- `/api/tournaments` - Collection
- `/api/tournaments/{id}` - Specific resource
- `/api/tournaments/{id}/team_assignments` - Sub-resource
- `/api/annual_championship` - Calculated resource

#### 5.1.2 HTTP Methods
- **GET**: Retrieve data (safe, idempotent)
- **POST**: Create new resource or trigger action
- **PUT**: Update existing resource (idempotent)
- **DELETE**: Remove resource

#### 5.1.3 Response Format
**Standard JSON Structure**:
```json
{
  "data": {...},           // Primary response data
  "metadata": {...},       // Additional context
  "error": null           // Error message if applicable
}
```

**Pagination** (for collections):
```json
{
  "data": [...],
  "pagination": {
    "total": 100,
    "page": 1,
    "perPage": 20,
    "totalPages": 5
  }
}
```

### 5.2 Error Responses

#### Standard Error Format
```json
{
  "error": "Error message",
  "code": "ERROR_CODE",
  "details": {...},
  "requestId": "uuid",
  "timestamp": "2026-04-11T10:30:00Z"
}
```

#### Common Status Codes
- **200 OK**: Successful GET, PUT
- **201 Created**: Successful POST (resource created)
- **204 No Content**: Successful DELETE
- **400 Bad Request**: Invalid input, validation error
- **404 Not Found**: Resource does not exist
- **429 Too Many Requests**: Rate limit exceeded
- **500 Internal Server Error**: Server-side error
- **503 Service Unavailable**: External API unavailable

---

## 6. Data Models & Schema

### 6.1 Firestore Collections

#### 6.1.1 tournaments
**Document ID**: Auto-generated

```javascript
{
  name: string,              // "The Masters 2026"
  orgId: string,             // "1" (PGA Tour)
  tournId: string,           // "014"
  year: string,              // "2026"
  oddsId: string (optional), // SportsData.io tournament ID
  par: number (optional),    // Course par (default: 72)
  courseName: string (opt),  // "Augusta National Golf Club"
  startDate: timestamp (opt),
  endDate: timestamp (opt),
  
  // Status flags
  IsTournamentOfficial: boolean,  // Manually marked complete
  participatesInAnnual: boolean,  // Include in championship
  IsDraftStarted: boolean,        // Draft initiated
  IsDraftComplete: boolean,       // Draft finished
  oddsLocked: boolean,            // Odds locked for draft
  
  // Team assignments
  teams: [
    {
      teamId: string,             // Reference to global_teams
      teamName: string,
      golferNames: [string, ...] // 4 golfers
    }
  ],
  
  // Locked odds (if draft started)
  lockedOdds: {...},
  
  // Timestamps
  createdAt: timestamp,
  updatedAt: timestamp
}
```

#### 6.1.2 global_teams
**Document ID**: Auto-generated

```javascript
{
  teamName: string,              // "Alpha Squad"
  year: string,                  // "2026"
  createdAt: timestamp,
  updatedAt: timestamp,
  
  // Preferred golfer assignments per tournament
  preferredGolfers: {
    "tournamentDocId": [
      "Sam Burns",
      "Rory McIlroy",
      "Scottie Scheffler",
      "Viktor Hovland"
    ]
  }
}
```

#### 6.1.3 tournament_scores
**Document ID**: {tournamentDocId}

```javascript
{
  results: [
    {
      teamName: string,
      totalScore: number,
      round1Score: number,
      round2Score: number,
      round3Score: number,
      round4Score: number,
      players: [
        {
          name: string,
          status: string,       // "active", "cut", "wd"
          total: number,
          r1: {score: number, isLive: boolean, isPenalty: boolean},
          r2: {...},
          r3: {...},
          r4: {...},
          isCut: boolean,
          cutPenaltyScore: {...}
        }
      ],
      cutPlayersCount: number,
      penaltyStrokesApplied: number,
      worstRoundScores: {1: number, 2: number, 3: number, 4: number}
    }
  ],
  metadata: {
    calculatedAt: timestamp,
    par: number,
    dataHash: string,           // Hash of source data
    isOfficial: boolean,
    worstRoundScores: {...}
  }
}
```

#### 6.1.4 api_usage
**Document ID**: `rapidapi_stats`

```javascript
{
  daily_calls: number,
  monthly_calls: number,
  daily_limit: number,
  monthly_limit: number,
  last_reset: timestamp,
  call_history: [
    {timestamp: timestamp, endpoint: string, cached: boolean}
  ]
}
```

### 6.2 External API Data Models

#### 6.2.1 RapidAPI Leaderboard Response
```json
{
  "leaderboardRows": [
    {
      "firstName": "Sam",
      "lastName": "Burns",
      "status": "active",  // or "cut", "wd", "dq"
      "total": "-5",
      "thru": "F",  // or "18", "17*" (live)
      "currentRound": {"$numberInt": "1"},
      "currentRoundScore": "-5",  // or "E", "+3"
      "rounds": [
        {
          "roundId": {"$numberInt": "1"},
          "strokes": {"$numberInt": "67"},
          "scoreToPar": "-5",
          "courseName": "Augusta National Golf Club"
        }
      ]
    }
  ],
  "currentRound": {"$numberInt": "1"},
  "roundState": "complete",  // or "in_progress", "official"
  "date": {"$date": "2026-04-11T..."}
}
```

---

## 7. Infrastructure & Deployment

### 7.1 Hosting Platform

**Platform**: Google Cloud Run

**Configuration**:
- **Runtime**: Python 3.11+
- **CPU**: 1 vCPU
- **Memory**: 512 MB
- **Concurrency**: 80 requests per instance
- **Min Instances**: 0 (scale to zero)
- **Max Instances**: 10
- **Timeout**: 300 seconds

### 7.2 Environment Configuration

#### Production
- **URL**: `https://leaderboard-backend-628169335141.us-east1.run.app/api`
- **Region**: us-east1
- **Firestore**: Production database
- **Secrets**: Google Cloud Secret Manager

#### Staging
- **URL**: `https://leaderboard-backend-staging-1056126670188.us-east1.run.app/api`
- **Region**: us-east1
- **Firestore**: Staging database
- **Secrets**: Separate staging secrets

### 7.3 CI/CD Pipeline

**Tool**: GitHub Actions

**Workflow**:
1. **Trigger**: Push to `main` branch
2. **Build**: Create Docker container
3. **Test**: Run unit tests (if available)
4. **Deploy**: Push to Cloud Run production
5. **Verify**: Health check

**Deployment Steps**:
```yaml
- Authenticate with Google Cloud
- Build Docker image
- Push to Container Registry
- Deploy to Cloud Run
- Configure environment variables
- Run health check
```

### 7.4 Monitoring & Alerting

#### Monitoring Metrics
- Request count and latency (p50, p95, p99)
- Error rate and types
- Cache hit ratio
- External API call count
- Memory and CPU usage
- Active instance count

#### Alerts
- Error rate > 5% (5 minutes)
- API response time > 2s (p95)
- Rate limit > 18 calls/day
- Service unavailable
- Memory usage > 90%

---

## 8. Security & Compliance

### 8.1 Authentication & Authorization
**Current State**: No authentication required (public API)

**Future Enhancement**:
- API key authentication for admin endpoints
- OAuth 2.0 for user-specific data
- Role-based access control (RBAC)

### 8.2 Data Privacy
- No personally identifiable information (PII) stored
- Professional golfer names are public information
- No user accounts or personal data

### 8.3 Secrets Management
**Tool**: Google Cloud Secret Manager

**Secrets**:
- `rapidapi-key-clean`: RapidAPI API key
- `sportsdata-api-key`: SportsData.io API key
- `firebase-service-account`: Firebase Admin SDK credentials

**Access**:
- Cloud Run service account has read access
- Secrets accessed via environment variables
- Automatic rotation supported

---

## 9. Testing Requirements

### 9.1 Unit Testing
**Framework**: pytest

**Coverage Targets**:
- Code coverage: > 70%
- Core business logic: 100%

**Test Cases**:
- Score calculation algorithms
- Cut penalty logic
- Data parsing (MongoDB wrappers)
- Name normalization
- Error handling

### 9.2 Integration Testing

**Test Scenarios**:
- RapidAPI integration (mocked responses)
- Firestore CRUD operations
- Cache behavior
- Rate limiting enforcement
- Complete tournament workflows

### 9.3 Performance Testing

**Load Testing**:
- Simulate 100 concurrent users
- Measure response times under load
- Test cache performance
- Verify auto-scaling

---

## 10. Constraints & Assumptions

### 10.1 Technical Constraints
- RapidAPI rate limit: 20 calls/day
- Google Cloud Run constraints (memory, CPU, timeout)
- Firestore read/write quotas
- Python runtime limitations

### 10.2 Business Constraints
- Golf tournaments typically run Thursday - Sunday
- PGA Tour season: January - September
- Maximum 12 teams per tournament
- 4 golfers per team (fixed)

### 10.3 Assumptions
- RapidAPI provides accurate, timely data
- Firestore availability: 99.95%
- External API response times < 2 seconds
- Tournament data structure remains consistent
- Cut occurs after Round 2 (R2)
- Player names in RapidAPI match SportsData.io

---

## 11. Future Enhancements

### 11.1 Phase 2 Features
- WebSocket support for real-time updates
- GraphQL API option
- Player statistics and historical data
- Advanced analytics (predictive scoring)
- Multi-year historical data queries
- Swagger/OpenAPI documentation
- Automated testing suite
- Database backups and disaster recovery

### 11.2 Optimization Opportunities
- Redis for distributed caching
- Database query optimization
- CDN for static responses
- GraphQL for flexible data fetching
- Background jobs for score calculations
- Elasticsearch for advanced search

---

## 12. Acceptance & Sign-Off

### 12.1 Acceptance Criteria Summary
- All Critical and High priority requirements implemented
- API response times meet targets
- Rate limiting working correctly
- Score calculations 100% accurate
- All endpoints documented
- Error handling comprehensive
- Deployed to production successfully

### 12.2 Sign-Off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Backend Lead | | | |
| Product Owner | | | |
| QA Engineer | | | |
| DevOps Engineer | | | |

---

## Appendix A: API Endpoint Reference

### Complete Endpoint List

| Method | Endpoint | Purpose | Priority |
|--------|----------|---------|----------|
| GET | /api/rate_limit_status | Rate limit info | High |
| GET | /api/schedule | Tournament schedule | High |
| GET | /api/tournament_info | Tournament details | High |
| GET | /api/leaderboard | Raw leaderboard | Critical |
| GET | /api/tournaments/{id}/leaderboard | Tournament leaderboard with teams | Critical |
| GET | /api/player_odds | Player betting odds | High |
| GET | /api/tournaments/{id}/stored_scores | Cached scores | High |
| POST | /api/tournaments/{id}/recalculate_scores | Force recalc | Medium |
| GET | /api/global_teams | List global teams | High |
| POST | /api/global_teams | Create team | High |
| PUT | /api/global_teams/{id} | Update team | High |
| DELETE | /api/global_teams/{id} | Delete team | Medium |
| POST | /api/global_teams/copy_year | Copy teams to new year | Low |
| GET | /api/tournaments/{id}/team_assignments | Get assignments | Critical |
| PUT | /api/tournaments/{id}/team_assignments | Update assignments | Critical |
| POST | /api/tournaments/{id}/sync_teams | Sync from global | Medium |
| POST | /api/tournaments | Create tournament | Critical |
| GET | /api/tournaments | List tournaments | Critical |
| GET | /api/tournaments/{id} | Get tournament | Critical |
| PUT | /api/tournaments/{id}/teams | Update teams | High |
| POST | /api/tournaments/{id}/start_draft | Start draft | High |
| POST | /api/tournaments/{id}/lock_draft_odds | Lock odds | High |
| POST | /api/tournaments/{id}/complete_draft | Complete draft | High |
| GET | /api/tournaments/{id}/draft_status | Draft status | High |
| GET | /api/annual_championship | Championship standings | High |
| POST | /api/batch | Batch operations | Medium |

---

## Appendix B: Glossary

- **RapidAPI**: Third-party golf data provider (leaderboard source of truth)
- **SportsData.io**: Sports betting odds provider
- **Firestore**: Google Cloud NoSQL database
- **Cloud Run**: Google Cloud serverless container platform
- **Cache TTL**: Time-to-live (duration cache is valid)
- **Rate Limit**: Maximum API calls allowed per period
- **Score to Par**: Strokes relative to course par (-2, E, +3)
- **Best 3-of-4**: Team scoring using 3 lowest individual scores
- **Cut**: Tournament elimination (typically after R2)
- **NFD**: Unicode Normalization Form D (canonical decomposition)

---

## Appendix C: Document Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | April 11, 2026 | AI Assistant | Initial comprehensive backend BRD |
