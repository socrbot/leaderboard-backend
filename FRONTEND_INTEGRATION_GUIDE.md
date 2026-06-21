# Frontend Integration Guide: Live Tournaments in Annual Championship

## Overview

This guide provides complete specifications for implementing live tournament support in the annual championship feature on the frontend. The backend already supports including in-progress tournaments via the `includeInProgress` parameter.

## Problem Statement

Currently, the annual championship only displays completed tournaments because the frontend doesn't pass the `includeInProgress=true` parameter to the backend API. This guide details all frontend changes needed to display live tournament data.

---

## API Integration

### 1. Update API Calls

**Current API Call:**
```javascript
GET /api/annual_championship?year=2026
```

**Updated API Call:**
```javascript
GET /api/annual_championship?year=2026&includeInProgress=true
```

### 2. API Response Structure

The backend returns the following structure when `includeInProgress=true`:

```typescript
interface AnnualChampionshipResponse {
  standings: TeamStanding[];
  tournaments: TournamentInfo[];
  metadata: ChampionshipMetadata;
}

interface TeamStanding {
  teamName: string;
  totalScore: number;  // Cumulative stroke total (lower is better)
  tournaments: TournamentResult[];
}

interface TournamentResult {
  tournamentId: string;
  name: string;
  position: number;
  score: number;
}

interface TournamentInfo {
  tournamentId: string;
  name: string;
  completedAt: string;  // ISO 8601 timestamp
  isComplete: boolean;  // false for in-progress tournaments
  teamResults: TeamResult[];
}

interface TeamResult {
  teamName: string;
  position: number;
  score: number;
}

interface ChampionshipMetadata {
  calculatedAt: string;        // ISO 8601 timestamp
  tournamentCount: number;      // Total tournaments in standings
  teamCount: number;            // Total teams participating
  inProgressCount: number;      // Number of live tournaments
  totalTournamentsFound: number;
  skippedTournaments: SkippedTournament[];
}

interface SkippedTournament {
  id: string;
  name: string;
  reason: string;
}
```

---

## UI/UX Implementation

### 1. Visual Indicators for Live Tournaments

#### Tournament Status Badges

Display status badges for each tournament in the standings:

```jsx
function TournamentStatusBadge({ isComplete }) {
  if (isComplete) {
    return (
      <span className="badge badge-complete">
        <CheckIcon /> Official
      </span>
    );
  }
  return (
    <span className="badge badge-live">
      <LiveIcon className="pulse" /> LIVE
    </span>
  );
}
```

#### Recommended Styling

```css
.badge-live {
  background-color: #dc2626;
  color: white;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.badge-complete {
  background-color: #16a34a;
  color: white;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.pulse {
  animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
}

@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
}
```

### 2. Standings Summary Section

Display championship metadata at the top of the standings:

```jsx
function ChampionshipHeader({ metadata }) {
  const lastUpdated = new Date(metadata.calculatedAt).toLocaleString();
  
  return (
    <div className="championship-header">
      <h1>Annual Championship Standings - {year}</h1>
      
      <div className="championship-stats">
        <span>{metadata.tournamentCount} Tournaments</span>
        {metadata.inProgressCount > 0 && (
          <>
            <span className="separator">|</span>
            <span className="live-indicator">
              {metadata.inProgressCount} In Progress
            </span>
          </>
        )}
        <span className="separator">|</span>
        <span>Last updated: {lastUpdated}</span>
        <button 
          onClick={handleRefresh} 
          className="refresh-button"
          aria-label="Refresh standings"
        >
          <RefreshIcon />
        </button>
      </div>
      
      {metadata.inProgressCount > 0 && (
        <div className="warning-banner">
          ⚠️ Standings include {metadata.inProgressCount} in-progress 
          tournament{metadata.inProgressCount > 1 ? 's' : ''} and are 
          subject to change
        </div>
      )}
    </div>
  );
}
```

### 3. Tournament List Display

Show each tournament with its status:

```jsx
function TournamentListItem({ tournament }) {
  const completedDate = tournament.isComplete 
    ? new Date(tournament.completedAt).toLocaleDateString()
    : null;
  
  return (
    <div className="tournament-item">
      <div className="tournament-header">
        <h3>{tournament.name}</h3>
        <TournamentStatusBadge isComplete={tournament.isComplete} />
      </div>
      
      {tournament.isComplete && completedDate && (
        <div className="tournament-date">
          Completed {completedDate}
        </div>
      )}
      
      <div className="tournament-results">
        {tournament.teamResults.map((result, index) => (
          <div key={result.teamName} className="team-result">
            <span className="position">{result.position}</span>
            <span className="team-name">{result.teamName}</span>
            <span className="score">
              {result.score > 0 ? '+' : ''}{result.score}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
```

---

## Auto-Refresh Implementation

### 1. Polling Strategy

Implement automatic refresh when live tournaments exist:

```javascript
function useAnnualChampionship(year) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  
  const fetchData = useCallback(async (forceRefresh = false) => {
    try {
      setLoading(true);
      const refreshParam = forceRefresh ? '&refresh=true' : '';
      const response = await fetch(
        `/api/annual_championship?year=${year}&includeInProgress=true${refreshParam}`
      );
      
      if (!response.ok) {
        throw new Error('Failed to fetch championship data');
      }
      
      const result = await response.json();
      setData(result);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [year]);
  
  // Initial fetch
  useEffect(() => {
    fetchData();
  }, [fetchData]);
  
  // Auto-refresh when live tournaments exist
  useEffect(() => {
    if (!data || data.metadata.inProgressCount === 0) {
      return; // No auto-refresh needed
    }
    
    // Poll every 3 minutes when live tournaments exist
    const intervalId = setInterval(() => {
      fetchData(false); // Use cache if available
    }, 3 * 60 * 1000); // 3 minutes
    
    return () => clearInterval(intervalId);
  }, [data, fetchData]);
  
  const manualRefresh = useCallback(() => {
    fetchData(true); // Force refresh
  }, [fetchData]);
  
  return { data, loading, error, refresh: manualRefresh };
}
```

### 2. Debounced Manual Refresh

Prevent excessive manual refresh clicks:

```javascript
import { useState, useCallback } from 'react';

function useDebounce(delay = 5000) {
  const [isDebouncing, setIsDebouncing] = useState(false);
  
  const debounce = useCallback((callback) => {
    if (isDebouncing) {
      return;
    }
    
    setIsDebouncing(true);
    callback();
    
    setTimeout(() => {
      setIsDebouncing(false);
    }, delay);
  }, [isDebouncing, delay]);
  
  return { debounce, isDebouncing };
}

// Usage in component
function ChampionshipPage() {
  const { data, refresh } = useAnnualChampionship(2026);
  const { debounce, isDebouncing } = useDebounce(5000);
  
  const handleRefresh = () => {
    debounce(() => {
      refresh();
    });
  };
  
  return (
    <button 
      onClick={handleRefresh}
      disabled={isDebouncing}
    >
      {isDebouncing ? 'Refreshing...' : 'Refresh'}
    </button>
  );
}
```

---

## Optional: User Toggle Feature

Allow users to choose whether to include live tournaments:

```javascript
function AnnualChampionshipPage() {
  // Load preference from localStorage
  const [includeLive, setIncludeLive] = useState(() => {
    const saved = localStorage.getItem('includeLiveTournaments');
    return saved !== null ? JSON.parse(saved) : true; // Default to true
  });
  
  // Save preference when changed
  const handleToggle = (value) => {
    setIncludeLive(value);
    localStorage.setItem('includeLiveTournaments', JSON.stringify(value));
  };
  
  // Fetch data with current preference
  const url = `/api/annual_championship?year=${year}&includeInProgress=${includeLive}`;
  
  return (
    <div>
      <div className="view-options">
        <label>
          <input
            type="radio"
            name="viewMode"
            value="all"
            checked={includeLive}
            onChange={() => handleToggle(true)}
          />
          Show completed + live tournaments
        </label>
        
        <label>
          <input
            type="radio"
            name="viewMode"
            value="completed"
            checked={!includeLive}
            onChange={() => handleToggle(false)}
          />
          Show only completed tournaments
        </label>
      </div>
      
      {/* Championship standings display */}
    </div>
  );
}
```

---

## Error Handling

### 1. API Error Handling

```javascript
function useAnnualChampionship(year) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  
  const fetchData = async () => {
    try {
      const response = await fetch(
        `/api/annual_championship?year=${year}&includeInProgress=true`
      );
      
      if (response.status === 500) {
        throw new Error('Server error. Please try again later.');
      }
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const result = await response.json();
      
      // Handle case where API returns error in response body
      if (result.error) {
        throw new Error(result.error);
      }
      
      setData(result);
      setError(null);
    } catch (err) {
      console.error('Failed to fetch championship data:', err);
      setError(err.message);
      setData(null);
    }
  };
  
  return { data, error };
}
```

### 2. Display Error States

```jsx
function ChampionshipStandings() {
  const { data, loading, error } = useAnnualChampionship(2026);
  
  if (loading) {
    return <LoadingSpinner />;
  }
  
  if (error) {
    return (
      <div className="error-state">
        <ErrorIcon />
        <h3>Unable to load championship standings</h3>
        <p>{error}</p>
        <button onClick={refresh}>Try Again</button>
      </div>
    );
  }
  
  if (!data || data.standings.length === 0) {
    return (
      <div className="empty-state">
        <InfoIcon />
        <h3>No championship data available</h3>
        <p>No tournaments have been completed yet for this year.</p>
      </div>
    );
  }
  
  return <StandingsTable data={data} />;
}
```

### 3. Handle Skipped Tournaments

Display information about tournaments that were excluded:

```jsx
function SkippedTournamentsInfo({ skippedTournaments }) {
  if (!skippedTournaments || skippedTournaments.length === 0) {
    return null;
  }
  
  return (
    <details className="skipped-tournaments">
      <summary>
        {skippedTournaments.length} tournament(s) not included
      </summary>
      <ul>
        {skippedTournaments.map(tournament => (
          <li key={tournament.id}>
            <strong>{tournament.name}</strong>: {tournament.reason}
          </li>
        ))}
      </ul>
    </details>
  );
}
```

---

## Performance Considerations

### 1. Caching Strategy

The backend implements caching with different keys for `includeInProgress`:
- Cache key format: `annual_championship_{year}:inProgress:{true|false}`
- TTL: 10 minutes for tournament data
- Use `refresh=true` parameter to bypass cache

**Frontend Caching:**

```javascript
// Use React Query for advanced caching
import { useQuery } from '@tanstack/react-query';

function useAnnualChampionship(year, includeInProgress = true) {
  return useQuery({
    queryKey: ['annual-championship', year, includeInProgress],
    queryFn: async () => {
      const response = await fetch(
        `/api/annual_championship?year=${year}&includeInProgress=${includeInProgress}`
      );
      return response.json();
    },
    staleTime: 3 * 60 * 1000, // 3 minutes
    refetchInterval: (data) => {
      // Auto-refetch every 3 minutes if live tournaments exist
      return data?.metadata?.inProgressCount > 0 ? 3 * 60 * 1000 : false;
    }
  });
}
```

### 2. Rate Limit Awareness

The backend has API rate limits:
- Daily limit: 20 calls
- Monthly limit: 200 calls

**Best Practices:**
- Use the backend's caching (don't force refresh unnecessarily)
- Set appropriate polling intervals (3-5 minutes recommended)
- Stop auto-refresh when no live tournaments exist
- Debounce manual refresh buttons

### 3. Optimistic UI Updates

Prevent jarring changes during updates:

```javascript
function ChampionshipStandings() {
  const [displayData, setDisplayData] = useState(null);
  const { data, loading } = useAnnualChampionship(2026);
  
  useEffect(() => {
    if (data) {
      // Smooth transition for updates
      setTimeout(() => {
        setDisplayData(data);
      }, 100);
    }
  }, [data]);
  
  // Show loading indicator only on initial load
  if (!displayData && loading) {
    return <LoadingSpinner />;
  }
  
  return (
    <div>
      {loading && (
        <div className="updating-indicator">
          <RefreshIcon className="spin" /> Updating...
        </div>
      )}
      <StandingsTable data={displayData || data} />
    </div>
  );
}
```

---

## Testing Checklist

### Unit Tests

- [ ] API call with `includeInProgress=true` parameter
- [ ] API call with `includeInProgress=false` parameter
- [ ] Parse response correctly with live tournaments
- [ ] Parse response correctly with only completed tournaments
- [ ] Handle empty tournaments array
- [ ] Handle API errors gracefully
- [ ] Debounce functionality works correctly

### Integration Tests

- [ ] Display completed tournaments correctly
- [ ] Display live tournament badges
- [ ] Show metadata (tournament count, in-progress count)
- [ ] Display warning banner when live tournaments exist
- [ ] Manual refresh button works
- [ ] Auto-refresh triggers when live tournaments exist
- [ ] Auto-refresh stops when no live tournaments
- [ ] Toggle between view modes (if implemented)

### End-to-End Tests

- [ ] Load championship page with no tournaments
- [ ] Load championship page with only completed tournaments
- [ ] Load championship page with only in-progress tournaments
- [ ] Load championship page with mixed tournaments
- [ ] Verify auto-refresh updates standings
- [ ] Verify manual refresh forces data update
- [ ] Verify cache invalidation with refresh parameter
- [ ] Test with multiple years
- [ ] Test error states (API down, network error)

---

## Example Component Implementation

Complete example of a championship standings component:

```jsx
import React, { useState, useEffect, useCallback } from 'react';

function AnnualChampionshipPage({ year = 2026 }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  
  // Fetch championship data
  const fetchData = useCallback(async (forceRefresh = false) => {
    try {
      setIsRefreshing(true);
      const refreshParam = forceRefresh ? '&refresh=true' : '';
      const response = await fetch(
        `/api/annual_championship?year=${year}&includeInProgress=true${refreshParam}`
      );
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const result = await response.json();
      setData(result);
      setError(null);
      setLastUpdated(new Date());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      setIsRefreshing(false);
    }
  }, [year]);
  
  // Initial load
  useEffect(() => {
    fetchData();
  }, [fetchData]);
  
  // Auto-refresh when live tournaments exist
  useEffect(() => {
    if (!data || data.metadata.inProgressCount === 0) {
      return;
    }
    
    const intervalId = setInterval(() => {
      fetchData(false);
    }, 3 * 60 * 1000);
    
    return () => clearInterval(intervalId);
  }, [data, fetchData]);
  
  const handleManualRefresh = () => {
    if (!isRefreshing) {
      fetchData(true);
    }
  };
  
  if (loading) {
    return <div className="loading">Loading championship standings...</div>;
  }
  
  if (error) {
    return (
      <div className="error">
        <h3>Error loading standings</h3>
        <p>{error}</p>
        <button onClick={handleManualRefresh}>Try Again</button>
      </div>
    );
  }
  
  if (!data || data.standings.length === 0) {
    return (
      <div className="empty">
        <h3>No championship data available</h3>
        <p>No tournaments have been completed yet for {year}.</p>
      </div>
    );
  }
  
  const { standings, tournaments, metadata } = data;
  
  return (
    <div className="annual-championship">
      <header className="championship-header">
        <h1>Annual Championship Standings - {year}</h1>
        
        <div className="championship-stats">
          <span>{metadata.tournamentCount} Tournaments</span>
          {metadata.inProgressCount > 0 && (
            <>
              <span className="separator">|</span>
              <span className="live-count">
                <span className="live-dot"></span>
                {metadata.inProgressCount} In Progress
              </span>
            </>
          )}
          <span className="separator">|</span>
          <span>
            Last updated: {new Date(metadata.calculatedAt).toLocaleTimeString()}
          </span>
          <button
            onClick={handleManualRefresh}
            disabled={isRefreshing}
            className="refresh-btn"
            aria-label="Refresh standings"
          >
            <RefreshIcon className={isRefreshing ? 'spin' : ''} />
          </button>
        </div>
        
        {metadata.inProgressCount > 0 && (
          <div className="warning-banner">
            ⚠️ Standings include {metadata.inProgressCount} in-progress 
            tournament{metadata.inProgressCount > 1 ? 's' : ''} and are 
            subject to change
          </div>
        )}
      </header>
      
      <section className="standings-table">
        <h2>Team Standings</h2>
        <table>
          <thead>
            <tr>
              <th>Position</th>
              <th>Team</th>
              <th>Total Score</th>
              <th>Tournaments</th>
            </tr>
          </thead>
          <tbody>
            {standings.map((team, index) => (
              <tr key={team.teamName}>
                <td>{index + 1}</td>
                <td>{team.teamName}</td>
                <td>{team.totalScore > 0 ? '+' : ''}{team.totalScore}</td>
                <td>{team.tournaments.length}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      
      <section className="tournaments-section">
        <h2>Tournament Results</h2>
        <div className="tournament-list">
          {tournaments.map(tournament => (
            <div key={tournament.tournamentId} className="tournament-card">
              <div className="tournament-header">
                <h3>{tournament.name}</h3>
                {tournament.isComplete ? (
                  <span className="badge badge-complete">
                    ✓ Official
                  </span>
                ) : (
                  <span className="badge badge-live">
                    <span className="pulse-dot"></span> LIVE
                  </span>
                )}
              </div>
              
              {tournament.isComplete && (
                <div className="tournament-date">
                  Completed {new Date(tournament.completedAt).toLocaleDateString()}
                </div>
              )}
              
              <div className="team-results">
                {tournament.teamResults.slice(0, 5).map(result => (
                  <div key={result.teamName} className="result-row">
                    <span className="position">{result.position}</span>
                    <span className="team">{result.teamName}</span>
                    <span className="score">
                      {result.score > 0 ? '+' : ''}{result.score}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>
      
      {metadata.skippedTournaments.length > 0 && (
        <details className="skipped-info">
          <summary>
            {metadata.skippedTournaments.length} tournament(s) not included
          </summary>
          <ul>
            {metadata.skippedTournaments.map(t => (
              <li key={t.id}>
                <strong>{t.name}</strong>: {t.reason}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

export default AnnualChampionshipPage;
```

---

## Summary

This guide provides everything needed to implement live tournament support in the annual championship frontend. The backend is ready and requires no changes. The frontend needs to:

1. **Add `includeInProgress=true` parameter** to API calls
2. **Display live tournament indicators** (badges, icons)
3. **Show metadata** (tournament count, in-progress count, last updated)
4. **Implement auto-refresh** (3-5 minute intervals when live tournaments exist)
5. **Add manual refresh button** with debouncing
6. **Handle error states** gracefully
7. **Test thoroughly** with different tournament scenarios

The implementation is backwards compatible - removing `includeInProgress` will revert to the original behavior of showing only completed tournaments.
