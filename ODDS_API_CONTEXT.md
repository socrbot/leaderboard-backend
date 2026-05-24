# Odds API v4 Context (Integration Reference)

Last updated: 2026-05-24
Primary docs source: https://the-odds-api.com/liveapi/guides/v4/
Swagger reference: https://app.swaggerhub.com/apis-docs/the-odds-api/odds-api/4?view=uiDocs#/sports/get_v4_sports

## Host And Auth
- Base host: https://api.the-odds-api.com
- IPv6 host: https://ipv6-api.the-odds-api.com
- Authentication: query parameter apiKey on every request
- Expected backend env var name: ODDS_API_KEY

## Google Secret Manager Setup (Current)
- Secret name: OddsAPI
- Resource name: projects/1056126670188/secrets/OddsAPI
- Replication: Automatically replicated
- Encryption: Google-managed
- Rotation: Not scheduled
- Created: 2026-05-24 08:29:10 AM GMT-4
- Expiration: Never

Recommended mapping in Cloud Run deploy config:
- ODDS_API_KEY=OddsAPI:latest

Note:
- Secret values should never be copied into repo files, docs, or frontend environment variables.

## Core Endpoints To Use In This Project

### 1) List sports (free)
- GET /v4/sports/?apiKey={apiKey}
- Optional: all=true to include out-of-season sports
- Returns sport objects with fields like:
  - key
  - group
  - title
  - description
  - active
  - has_outrights
- Quota cost: 0

### 2) List events (free)
- GET /v4/sports/{sport}/events?apiKey={apiKey}
- Useful params:
  - dateFormat=iso|unix (default iso)
  - eventIds=comma,separated,ids
  - commenceTimeFrom=ISO8601
  - commenceTimeTo=ISO8601
  - includeRotationNumbers=true|false
- Quota cost: 0

### 3) Main odds feed (primary replacement)
- GET /v4/sports/{sport}/odds/?apiKey={apiKey}&regions={regions}&markets={markets}
- Useful params:
  - regions=us,us2,uk,eu,au (comma-separated)
  - markets=h2h,spreads,totals,outrights
  - oddsFormat=american|decimal (default decimal)
  - dateFormat=iso|unix (default iso)
  - eventIds=comma,separated,ids
  - bookmakers=comma,separated,keys
  - commenceTimeFrom / commenceTimeTo
  - includeLinks=true|false
  - includeSids=true|false
  - includeBetLimits=true|false
  - includeRotationNumbers=true|false
- Golf note: for sports with outright markets, default market can be outrights if markets not passed
- Quota cost: number_of_markets * number_of_regions
- Important: if no events are returned, call does not count against quota

### 4) Single-event odds (when you need prop depth)
- GET /v4/sports/{sport}/events/{eventId}/odds?apiKey={apiKey}&regions={regions}&markets={markets}
- Same parameter set as main odds endpoint plus:
  - includeMultipliers=true|false (DFS-specific)
- Quota cost: unique_markets_returned * number_of_regions
- Important: empty data does not count against quota

### 5) Participants (optional helper)
- GET /v4/sports/{sport}/participants?apiKey={apiKey}
- Returns participant whitelist for the sport (teams or individuals)
- Quota cost: 1

## Response Headers To Always Capture
- x-requests-remaining
- x-requests-used
- x-requests-last

Recommendation:
- Log these headers on every Odds API response
- Persist last seen values to monitor burn rate

## Response Shape Highlights

### Odds list response (main odds endpoint)
Each event includes:
- id
- sport_key
- sport_title (often present)
- commence_time
- home_team
- away_team
- bookmakers[]

Each bookmaker includes:
- key
- title
- last_update
- markets[]

Each market includes:
- key (for example h2h, spreads, totals, outrights)
- outcomes[]

Each outcome commonly includes:
- name
- price
- point (for spreads/totals and props where relevant)
- description (common on many prop/event-market responses)

## Suggested Defaults For Golf Outrights In This Codebase
- sport: golf_us_open_winner (or event-specific golf key from /sports)
- regions: us
- markets: outrights
- oddsFormat: american
- dateFormat: iso
- includeLinks: false (enable later only if needed)
- polling interval: 15-30 minutes for non-live drafting needs

## Mapping To Existing Leaderboard Backend Concepts
- Replace SportsData oddsId with Odds API event id where event-specific linking is required
- Keep DraftLockedOdds as the internal normalized structure used by frontend
- Recommended normalized player row:
  - name
  - averageOdds (from selected bookmaker aggregation)
  - oddsSource = odds_api
  - sourceEventId
  - sourceSportKey
  - sourceBookCount
  - lastSyncedAt

## Error Handling
- Rate limit status code: 429
- Handle transient upstream failures with retry + jitter (backend only)
- If response has no events/odds, treat as valid empty result, not an exception

## Quota Strategy For This App
- Use free endpoints first:
  - /sports to discover active golf key
  - /events to enumerate event IDs
- Query /odds with minimal scope during draft lock:
  - one region
  - one market (outrights)
- Avoid multi-region and multi-market until needed
- Record x-requests-* headers for every call and alert when remaining drops below threshold

## Practical Request Examples

### Sports
https://api.the-odds-api.com/v4/sports/?apiKey=YOUR_API_KEY

### Events (sport-specific)
https://api.the-odds-api.com/v4/sports/golf_us_open_winner/events?apiKey=YOUR_API_KEY&dateFormat=iso

### Outright odds
https://api.the-odds-api.com/v4/sports/golf_us_open_winner/odds/?apiKey=YOUR_API_KEY&regions=us&markets=outrights&oddsFormat=american

## Four Majors Data Sourcing Workflow (Implementation Plan)

Goal: reliably source outright winner odds for The Masters, PGA Championship, U.S. Open, and The Open Championship using one repeatable backend pipeline.

### Step 1: Discover in-season golf sports (zero-cost call)
- Call: GET /v4/sports/?apiKey={apiKey}
- Filter returned rows to candidates where:
  - active == true
  - has_outrights == true
  - key starts with golf_
- Build a candidate cache with fields:
  - key
  - title
  - group
  - active
  - has_outrights
  - discoveredAt

Reliability guardrails:
- If no golf candidates are returned, keep last known-good mapping and fail closed (do not overwrite current mapping with empty data).
- Refresh discovery cache every 6 to 24 hours (not every request).

### Step 2: Match each major to a sport_key
- Maintain a canonical majors registry in backend config:
  - masters
  - pga_championship
  - us_open
  - open_championship
- For each major, match against discovered sports using normalized comparisons of title/key synonyms.

Suggested matching strategy:
1. Exact key match from prior known mapping (highest confidence)
2. Exact normalized title match (for example "us open")
3. Keyword scoring on key + title (for example [golf, open, winner])
4. Manual fallback map for known keys if discovery names drift

Expected output object:
- majorCode
- sportKey
- confidence (exact_key | exact_title | fuzzy | fallback)
- matchedFrom (which field/rule won)
- matchedAt

Hard validation rules:
- Must resolve all 4 majors before marking mapping as healthy.
- If fewer than 4 resolve, surface a warning and keep previous mapping for unresolved majors.

### Step 3: Pull outright odds from resolved sport_key
- Call per major:
  - GET /v4/sports/{sport_key}/odds/?apiKey={apiKey}&regions=us&markets=outrights&oddsFormat=american&dateFormat=iso
- Parse event list and bookmaker markets.
- Normalize into internal DraftLockedOdds-compatible rows.

Recommended normalized row shape:
- name
- averageOdds
- bestOdds
- worstOdds
- source = odds_api
- sourceMajor = masters | pga_championship | us_open | open_championship
- sourceSportKey
- sourceEventId
- sourceBookCount
- lastSyncedAt

### Quota-safe polling policy
- Discovery (/sports): every 6 to 24 hours (cost 0)
- Optional /events checks: every 6 to 24 hours (cost 0)
- /odds polling:
  - Draft prep window: every 15 to 30 minutes
  - Outside draft window: every 2 to 6 hours
  - During manual lock operation: one on-demand refresh before lock

### Data quality checks before publish
- Reject payload if no events were returned for a mapped major and previous data exists (keep previous snapshot).
- Require a minimum bookmaker count threshold (for example >= 3) before replacing current snapshot.
- Drop clearly invalid player outcomes (blank names, non-numeric prices).
- Log x-requests-remaining, x-requests-used, x-requests-last for each odds call.

### Storage and compatibility in this codebase
- Keep existing Firestore fields for now:
  - oddsId (legacy)
  - DraftLockedOdds (current frontend contract)
- Add new fields during migration:
  - oddsSportKey
  - oddsEventId
  - oddsSourceVersion
  - oddsLastSyncAt
  - oddsSyncStatus

### Minimal implementation phases
1. Discovery and mapping layer only (no frontend changes)
2. Odds fetch + normalization layer (write to DraftLockedOdds)
3. Draft lock routes switch to Odds API provider
4. Remove SportsData dependencies after one full major cycle validates parity

## Migration Notes (SportsData -> Odds API)
- Keep old fields temporarily for backward compatibility while migrating frontend
- Add an odds source marker in responses to simplify observability
- Use one adapter layer in backend so downstream code does not depend on raw provider payload shapes

## Source Notes
- This file was built from the public v4 docs and aligned to the Swagger entrypoint above.
- If Swagger and guide text diverge, prefer live behavior verified by test calls in staging.
