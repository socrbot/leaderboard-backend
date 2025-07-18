# Backend Changes - Backwards Compatibility Analysis & Firestore Schema

## 🔄 **Backwards Compatibility Analysis**

### ✅ **FULLY BACKWARDS COMPATIBLE**

The backend changes are designed to be **100% backwards compatible** with your existing frontend and database. Here's why:

#### **Existing API Endpoints - UNCHANGED**
- All existing routes maintain the same URL structure
- Response formats remain identical for legacy calls
- Default parameter values ensure old API calls work exactly as before

#### **Database Schema - ADDITIVE ONLY**
- No existing fields are modified or removed
- All new fields have default values
- Legacy data structures are preserved and supported

#### **New Features - OPT-IN**
- Team score calculations are **optional** (via `calculateTeams=true` parameter)
- New endpoints are **additional**, not replacements
- Enhanced data is **added to** existing responses, not replacing them

### 📊 **API Compatibility Matrix**

| Endpoint | Compatibility | Changes | Impact |
|----------|---------------|---------|---------|
| `/api/leaderboard` | ✅ **FULL** | Enhanced with optional team calculations | Zero - works exactly as before |
| `/api/player_odds` | ✅ **FULL** | Added draft lock functionality | Zero - falls back to live odds |
| `/api/tournaments` | ✅ **FULL** | Added new fields with defaults | Zero - legacy fields preserved |
| `/api/tournaments/{id}` | ✅ **FULL** | Enhanced status detection | Zero - existing fields unchanged |
| `/api/tournaments/{id}/teams` | ✅ **FULL** | Enhanced validation | Zero - accepts same data format |

#### **New Endpoints (Non-breaking)**
- `/api/rate_limit_status` - NEW
- `/api/schedule` - NEW  
- `/api/tournament_info` - NEW
- `/api/annual_championship` - NEW
- `/api/global_teams` - NEW

---

## 🗄️ **Complete Firestore Database Schema**

### **Collection: `tournaments`**

```json
{
  "tournamentId": "auto-generated-doc-id",
  "data": {
    // CORE TOURNAMENT DATA (Existing)
    "name": "Tournament Name",
    "orgId": "1",                    // PGA Tour organization ID
    "tournId": "033",                // Tournament ID from RapidAPI
    "year": "2025",                  // Tournament year
    "oddsId": "12345",               // SportsData.io odds ID
    "par": 71,                       // Course par (default: 71)
    
    // TEAM MANAGEMENT (Existing - Legacy Support)
    "teams": [                       // Legacy team structure (maintained for compatibility)
      {
        "teamName": "Team Alpha",
        "golferNames": [
          "Tiger Woods",
          "Rory McIlroy", 
          "Jon Rahm",
          "Scottie Scheffler"
        ],
        "participatesInAnnual": true,
        "draftOrder": 1
      }
    ],
    
    // GLOBAL TEAM REFERENCES (New - Enhanced)
    "teamAssignments": [             // References to global_teams collection
      {
        "globalTeamId": "team-doc-id",
        "assignedAt": "2025-07-18T10:30:00Z"
      }
    ],
    
    // DRAFT MANAGEMENT (New)
    "IsDraftStarted": false,         // Whether draft has begun
    "IsDraftComplete": false,        // Whether draft is finished
    "DraftLockedOdds": [],           // Locked odds when draft starts
    "DraftOddsLockedAt": "timestamp", // When odds were locked
    
    // STATUS TRACKING (New)
    "isComplete": false,             // Tournament completion status
    "isActive": true,                // Currently in progress
    "completedAt": "timestamp",      // When tournament finished
    "finalStatus": "Official",       // Final tournament status
    "lastStatusCheck": "timestamp",  // Last automated status check
    
    // METADATA (Existing)
    "createdAt": "firestore-timestamp",
    "updatedAt": "firestore-timestamp"
  }
}
```

### **Collection: `tournament_scores` (New)**

```json
{
  "scoreSnapshotId": "tournamentId_latest",
  "data": {
    // TOURNAMENT REFERENCE
    "tournamentId": "tournament-doc-id",
    
    // CALCULATED TEAM SCORES
    "teamScores": [
      {
        "teamName": "Team Alpha",
        "totalScore": 15,
        "players": [...],              // Detailed player data with cut penalties
        "cutPlayersCount": 1,
        "penaltyStrokesApplied": 2,
        "cutPenaltyScore": 12,
        "highestNonCutScore": 11,
        "validRounds": 4,
        "roundDetails": {...}
      }
    ],
    
    // LEADERBOARD SNAPSHOT
    "leaderboardData": {
      "leaderboardRows": [...],        // Full leaderboard data when calculated
      "tournamentStatus": {
        "status": "Official",
        "isOfficialComplete": true,
        "lastUpdated": "2025-07-18T15:30:00Z"
      },
      "roundId": 4
    },
    
    // CALCULATION METADATA
    "metadata": {
      "par": 71,
      "teamCount": 8,
      "playerCount": 156,
      "calculatedAt": "2025-07-18T15:30:00Z",
      "fromStorage": false,
      "forceRecalculated": false
    },
    
    // DATA INTEGRITY
    "dataHash": "md5-hash-of-leaderboard-data",
    "calculatedAt": "firestore-timestamp",
    "isOfficialComplete": true,
    "roundId": 4
  }
}
```

### **Enhanced Collection: `tournaments` (Score Storage Fields)**

```json
{
  "tournamentId": "auto-generated-doc-id", 
  "data": {
    // ... existing tournament fields ...
    
    // STORED SCORE CACHE (New)
    "lastCalculatedScores": [...],    // Most recent team scores
    "lastScoreCalculation": "timestamp", // When scores were last calculated
    "lastScoreMetadata": {            // Metadata from last calculation
      "par": 71,
      "teamCount": 8,
      "calculatedAt": "2025-07-18T15:30:00Z"
    }
  }
}
```

```json
{
  "teamId": "auto-generated-doc-id",
  "data": {
    // TEAM IDENTITY
    "name": "Team Alpha",           // Unique team name
    
    // TEAM COMPOSITION  
    "golferNames": [                // Array of golfer full names
      "Tiger Woods",
      "Rory McIlroy",
      "Jon Rahm", 
      "Scottie Scheffler"
    ],
    
    // TOURNAMENT PARTICIPATION
    "participatesInAnnual": true,   // Eligible for annual championship
    "draftOrder": 1,                // Draft pick order
    
    // METADATA
    "createdAt": "firestore-timestamp",
    "updatedAt": "firestore-timestamp"
  }
}
```

### **Enhanced Tournament Response Schema**

When requesting tournament data, you now receive:

```json
{
  // EXISTING DATA (Unchanged)
  "id": "tournament-doc-id",
  "name": "Tournament Name",
  "orgId": "1",
  "tournId": "033", 
  "year": "2025",
  "teams": [...],                   // Legacy teams array
  
  // ENHANCED STATUS DATA (New)
  "IsInProgress": true,             // Live tournament status
  "IsOver": false,                  // Tournament completion
  "par": 71,                        // Current par
  "status": "In Progress",          // Live status from API
  
  // DRAFT STATUS (New)
  "IsDraftStarted": false,
  "IsDraftComplete": false,
  
  // LIVE TOURNAMENT DATA (New)
  "Tournament": {                   // Live data from SportsData.io
    "IsInProgress": true,
    "IsOver": false,
    "Par": 71,
    "Status": "In Progress"
  }
}
```

### **Enhanced Leaderboard Response Schema**

When requesting leaderboard with team calculations:

```json
{
  // STANDARD RAPIDAPI DATA (Unchanged)
  "tournId": "033",
  "roundId": 4,
  "status": "Official",
  "leaderboardRows": [...],         // Standard player data
  
  // ENHANCED STATUS (New)
  "tournamentStatus": {
    "status": "Official",
    "isOfficialComplete": true,
    "isInProgress": false,
    "lastUpdated": "2025-07-18T15:30:00Z"
  },
  
  // TEAM CALCULATIONS (New - Optional)
  "teamScores": [
    {
      "teamName": "Team Alpha",
      "totalScore": 15,               // Team total score
      "players": [                    // Individual player details
        {
          "name": "Tiger Woods",
          "status": "active",
          "total": 5,
          "isCut": false,
          "r1": {"score": 2, "isLive": false, "isPenalty": false},
          "r2": {"score": 1, "isLive": false, "isPenalty": false},
          "r3": {"score": 3, "isLive": false, "isPenalty": false}, 
          "r4": {"score": -1, "isLive": false, "isPenalty": false}
        },
        {
          "name": "John Doe",          // Cut player example
          "status": "cut",
          "total": 12,                 // Penalty score applied
          "isCut": true,
          "cutPenaltyScore": 12,
          "r1": {"score": 4, "isLive": false, "isPenalty": false},
          "r2": {"score": 8, "isLive": false, "isPenalty": false},
          "r3": {"score": 12, "isLive": false, "isPenalty": true},
          "r4": {"score": 12, "isLive": false, "isPenalty": true}
        }
      ],
      "cutPlayersCount": 1,
      "penaltyStrokesApplied": 2,     // Number of penalty rounds applied
      "cutPenaltyScore": 12,          // Highest non-cut score + 1
      "highestNonCutScore": 11,       // Reference score for penalty
      "validRounds": 4,
      "roundDetails": {               // Per-round breakdown
        "r1": {"score": 6, "penaltyScores": 0, "validScores": 4},
        "r2": {"score": 9, "penaltyScores": 0, "validScores": 4},
        "r3": {"score": 15, "penaltyScores": 1, "validScores": 4},
        "r4": {"score": 11, "penaltyScores": 1, "validScores": 4}
      }
    }
  ],
  
  // CALCULATION METADATA (New)
  "teamCalculationMetadata": {
    "par": 71,
    "teamCount": 8,
    "playerCount": 156,
    "calculatedAt": "2025-07-18T15:30:00Z"
  }
}
```

---

## 🔧 **Migration Strategy**

### **Zero-Downtime Deployment**
1. **Deploy backend** - All existing calls continue working
2. **Test new endpoints** - Verify enhanced functionality  
3. **Gradually migrate frontend** - Update components one by one
4. **Enable new features** - Add team calculations where needed

### **Database Migration**
**NO MIGRATION REQUIRED** - All new fields have defaults and are optional.

### **Frontend Updates (Optional)**
```javascript
// OLD CALL (still works exactly the same)
const leaderboard = await fetch('/api/leaderboard?tournId=033&year=2025');

// NEW ENHANCED CALL (opt-in to team calculations)
const enhancedLeaderboard = await fetch('/api/leaderboard?tournId=033&year=2025&calculateTeams=true&tournamentId=doc123');
```

### **Rollback Plan**
- **Easy rollback** - Simply deploy previous version
- **No data loss** - New fields are additive only
- **Instant recovery** - No database changes to undo

---

## 🎯 **Key Benefits of This Approach**

1. **Zero Risk** - Existing functionality untouched
2. **Gradual Adoption** - Use new features when ready
3. **Enhanced Performance** - Better caching and rate limiting
4. **Future-Proof** - Ready for new features and scaling
5. **Improved Accuracy** - Correct cut player penalty calculation

The backend changes are designed as **enhancements** rather than **replacements**, ensuring your existing system continues to work flawlessly while providing new capabilities when you're ready to use them.
