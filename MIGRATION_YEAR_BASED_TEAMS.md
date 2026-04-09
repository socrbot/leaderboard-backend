# Year-Based Global Teams Migration Guide

**Date**: April 8, 2026  
**Branch**: staging  
**Status**: Ready for testing

---

## Overview

This update changes global teams from being shared across all years to being year-specific. Each season now has its own independent set of teams.

### Key Changes

1. **Global Teams are Year-Specific**
   - Each team now has a `year` field (e.g., "2025", "2026")
   - Teams for 2025 are separate from teams for 2026
   - UI shows current year in header (controlled by banner year selector)

2. **Annual Championship Uses Year-Specific Teams**
   - Queries global_teams collection directly to check `participatesInAnnual`
   - Only includes teams that match the selected year
   - No more stale data issues

3. **Copy Teams Feature**
   - One-click button to copy previous year's teams to current year
   - Golfer assignments are cleared (ready for new draft)
   - Preserves team names and participatesInAnnual settings

4. **Removed from Draft Management**
   - "Annual Championship Participant" checkbox removed from Draft Management
   - This setting is now managed only in Global Teams setup

---

## Migration Steps

### Phase 1: Database Migration (REQUIRED BEFORE DEPLOYMENT)

Run the migration script **on staging** to add year field to existing teams:

```bash
cd leaderboard-backend
python migrate_teams_add_year.py
```

This will:
- Find all global_teams without a 'year' field
- Prompt you for which year to assign (default: 2025)
- Add `year: "2025"` to all existing teams

### Phase 2: Deploy to Staging

The code has already been committed and pushed to staging branches.

**Backend**: 
```bash
git checkout staging
git pull
# Deploy backend to staging environment
```

**Frontend**:
```bash
git checkout staging  
git pull
# Deploy frontend to staging environment
```

### Phase 3: Test on Staging

1. **Test Global Teams for 2025**
   - Select 2025 in banner
   - Go to Setup → Global Teams
   - Verify existing teams appear
   - Verify you can edit participatesInAnnual

2. **Test Global Teams for 2026**
   - Select 2026 in banner
   - Go to Setup → Global Teams
   - Should be empty (no teams yet for 2026)
   - Click "Copy Teams from 2025"
   - Verify teams are copied with empty golfer lists

3. **Test Tournament Creation**
   - Select 2026 in banner
   - Create a new tournament
   - Verify only 2026 teams are auto-assigned

4. **Test Annual Championship**
   - Select 2025 → View Annual Championship
   - Should show 2025 teams only
   - Select 2026 → View Annual Championship
   - Should be empty or show only 2026 tournament results

5. **Test Participation Changes**
   - Go to Global Teams for 2026
   - Toggle a team's "Annual Championship" checkbox
   - Create/view Annual Championship
   - Verify the change is reflected immediately

### Phase 4: Production Migration (AFTER STAGING VALIDATION)

1. **Create Production Backup**
   ```bash
   # Use Firestore backup or export
   gcloud firestore export gs://your-bucket/backup-$(date +%Y%m%d)
   ```

2. **Run Migration on Production**
   ```bash
   # Set GOOGLE_APPLICATION_CREDENTIALS to production service account
   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/production-service-account.json
   python migrate_teams_add_year.py
   ```

3. **Deploy to Production**
   - Merge staging to main/master
   - Deploy backend and frontend

4. **Verify Production**
   - Test all scenarios from Phase 3

---

## Code Changes Summary

### Backend (leaderboard-backend/app.py)

**GET /api/global_teams**
- Added `year` query parameter
- Filters teams by year: `.where('year', '==', year)`

**POST /api/global_teams**  
- Now requires `year` in request body
- Checks for duplicate names within same year only

**PUT /api/global_teams/<team_id>**
- Updated duplicate name check to be year-specific

**POST /api/global_teams/copy_year** (NEW)
- Copies all teams from one year to another
- Clears golfer assignments
- Returns error if target year already has teams

**POST /api/tournaments**
- Updated to only fetch global teams for tournament's year
- Auto-assigns year-specific teams

**GET /api/annual_championship**
- Now queries global_teams directly for participatesInAnnual
- Only includes teams matching selected year
- Falls back to legacy teams data if global team lookup fails

### Frontend

**App.js**
- Passes `selectedYear` prop to Setup component

**Setup.js**
- Accepts `selectedYear` prop
- Passes it to GlobalTeamsManagement component

**GlobalTeamsManagement.js**
- Accepts `selectedYear` prop
- Fetches teams for selected year only
- Includes year in team creation requests
- Shows year in header: "Global Teams Management - 2026 Season"
- Shows "Copy Teams from YYYY" button when no teams exist
- Implements handleCopyFromPreviousYear function

**TeamManagement.js**
- Removed "Annual Championship Participant" checkbox
- Removed handleAnnualParticipationChange function

---

## User Workflow Changes

### Before (Old System)
1. Global teams apply to all years
2. Changes to participatesInAnnual affect all years
3. Team roster can't change between years
4. Checkbox in Draft Management (confusing location)

### After (New System)
1. Select year in banner (e.g., 2026)
2. Go to Setup → Global Teams
3. See teams for selected year only
4. Copy from previous year to start new season
5. Modify team list and participation as needed
6. Changes only affect selected year

---

## Rollback Plan

If issues are found after deployment:

1. **Revert Code**
   ```bash
   # Backend
   cd leaderboard-backend
   git checkout main
   git push origin main
   
   # Frontend  
   cd leaderboard
   git checkout master
   git push origin master
   ```

2. **Restore Database Backup** (if migration was run)
   ```bash
   gcloud firestore import gs://your-bucket/backup-YYYYMMDD
   ```

3. **Redeploy** previous version

---

## Troubleshooting

### No teams appear after migration
- Check that migration script ran successfully
- Verify teams have `year` field in Firestore console
- Check browser console for API errors

### Teams from wrong year appearing
- Verify selectedYear prop is passed correctly
- Check API request includes `?year=YYYY` parameter
- Verify backend year filter is working

### Annual Championship shows wrong teams
- Check global_teams have correct participatesInAnnual values
- Verify year field matches tournament year
- Check browser console for API errors

### Copy Teams button doesn't work
- Verify previous year has teams
- Check if target year already has teams (must delete first)
- Check backend logs for errors

---

## Testing Checklist

- [ ] Migration script runs without errors
- [ ] Existing 2025 teams have `year: "2025"` field
- [ ] Can view 2025 teams in Global Teams setup
- [ ] Can view empty 2026 teams list
- [ ] Can copy teams from 2025 to 2026
- [ ] Copied teams have empty golferNames
- [ ] Can create 2026 tournament with 2026 teams
- [ ] Can toggle participatesInAnnual in Global Teams
- [ ] Annual Championship respects participatesInAnnual changes
- [ ] Annual Championship shows correct year's teams
- [ ] Draft Management no longer has Annual Championship checkbox
- [ ] Year shown in Global Teams header

---

## Next Steps

After successful staging validation:
1. Schedule production deployment
2. Notify users of new year-based team management
3. Create user guide for setting up new season
4. Monitor for issues

## Support

If you encounter issues:
1. Check Firestore Console for data integrity
2. Review backend logs for API errors
3. Check browser console for frontend errors
4. Verify all environment variables are set correctly
