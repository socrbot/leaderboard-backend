import firebase_admin
from firebase_admin import credentials, firestore
import os
from datetime import datetime, timezone

os.environ['GOOGLE_CLOUD_PROJECT'] = 'alumni-golf-tournament'
cred = credentials.ApplicationDefault()
firebase_admin.initialize_app(cred, {'projectId': 'alumni-golf-tournament'})
db = firestore.client()

TOURN_ID = '1yRK1FAq9AqKQp3goX91'

# Load stored leaderboard rows
scores_doc = db.collection('tournament_scores').document(TOURN_ID + '_latest').get().to_dict()
lb_data = scores_doc.get('leaderboardData', {})
rows = lb_data.get('leaderboardRows', [])
print(f'Player rows available: {len(rows)}')

def parse_score(s):
    if s in ('E', '', None): return 0
    try: return int(s)
    except: return 0

# Build player lookup
player_scores = {}
for r in rows:
    full_name = (r.get('firstName', '') + ' ' + r.get('lastName', '')).strip()
    player_scores[full_name] = {
        'total': parse_score(r.get('total', 'E')),
        'position': r.get('position', '99'),
        'status': r.get('status', ''),
        'rounds': r.get('rounds', [])
    }

print(f'Players indexed: {len(player_scores)}')

# Load teams
tourn_doc = db.collection('tournaments').document(TOURN_ID).get().to_dict()
teams = tourn_doc.get('teams', [])
par = tourn_doc.get('par', 70)
print(f'Teams: {len(teams)}, Par: {par}')

# Compute best-3-of-4
team_scores = []
for team in teams:
    name = team.get('name', '')
    golfers = team.get('golferNames', [])
    picks = []
    for g in golfers:
        if g in player_scores:
            picks.append({'playerName': g, **player_scores[g]})
        else:
            picks.append({'playerName': g, 'total': 8, 'position': 'CUT', 'status': 'cut', 'rounds': []})
    picks_sorted = sorted(picks, key=lambda x: x['total'])
    best3 = picks_sorted[:3]
    total = sum(p['total'] for p in best3)
    team_scores.append({
        'name': name,
        'totalScore': total,
        'golfers': picks,
        'ownerUid': team.get('ownerUid', '')
    })

team_scores.sort(key=lambda x: x['totalScore'])

print('\nResults:')
for i, t in enumerate(team_scores):
    best = sorted(t['golfers'], key=lambda x: x['total'])[:3]
    best_str = ', '.join(f"{g['playerName']}:{g['total']}" for g in best)
    print(f"  {i+1}. {t['name']}: {t['totalScore']} ({best_str})")

# Write back to Firestore
db.collection('tournament_scores').document(TOURN_ID + '_latest').update({
    'teamScores': team_scores,
    'calculatedAt': datetime.now(timezone.utc).isoformat(),
})
print(f'\nWrote {len(team_scores)} team scores to tournament_scores/{TOURN_ID}_latest')
