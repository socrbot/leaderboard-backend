"""Recompute 2026 PGA Championship team scores using the correct per-round best-3-of-4 logic."""
import firebase_admin
from firebase_admin import credentials, firestore
import os, re, unicodedata
from datetime import datetime, timezone

os.environ['GOOGLE_CLOUD_PROJECT'] = 'alumni-golf-tournament'
cred = credentials.ApplicationDefault()
firebase_admin.initialize_app(cred, {'projectId': 'alumni-golf-tournament'})
db = firestore.client()

TOURN_ID = '1yRK1FAq9AqKQp3goX91'

# --- Load data ---
scores_raw = db.collection('tournament_scores').document(TOURN_ID + '_latest').get().to_dict()
lb_data = scores_raw.get('leaderboardData', {})
rows = lb_data.get('leaderboardRows', [])
print(f'Leaderboard rows: {len(rows)}')

tourn = db.collection('tournaments').document(TOURN_ID).get().to_dict()
teams = tourn.get('teams', [])
par = tourn.get('par', 70)
print(f'Teams: {len(teams)}, Par: {par}')


# --- Helpers ---
def unwrap(v):
    """Unwrap MongoDB Extended JSON values like {'$numberInt': '3'} -> 3"""
    if isinstance(v, dict):
        if '$numberInt' in v: return int(v['$numberInt'])
        if '$numberLong' in v: return int(v['$numberLong'])
        if '$numberDouble' in v: return float(v['$numberDouble'])
    return v

def parse_score_to_par(s):
    if s in ('E', '', None): return 0
    if isinstance(s, dict): s = unwrap(s)
    try: return int(s)
    except: return 0

def normalize(name):
    # Strip diacritics (ø→o, Å→a, é→e, etc.) then lowercase/collapse spaces
    nfkd = unicodedata.normalize('NFKD', name or '')
    ascii_name = ''.join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r'[\s\-]+', ' ', ascii_name.lower().strip())

def get_round_score(player, round_num):
    """Get score-to-par for a specific round, or None if not played."""
    rounds = player.get('rounds', [])
    for r in rounds:
        rid = unwrap(r.get('roundId', 0))
        if rid == round_num:
            return parse_score_to_par(r.get('scoreToPar'))
    return None

# --- Build player index ---
player_index = {}
for p in rows:
    full = normalize(f"{p.get('firstName','')} {p.get('lastName','')}")
    if full:
        player_index[full] = p

# --- Worst score per round for cut penalty ---
worst = {1: None, 2: None, 3: None, 4: None}
for rnum in [1, 2, 3, 4]:
    scores = []
    for p in rows:
        if (p.get('status') or '').lower() != 'cut':
            s = get_round_score(p, rnum)
            if s is not None:
                scores.append(s)
    if scores:
        worst[rnum] = max(scores) + 1
print(f'Worst round scores (penalty): {worst}')

# --- Compute team scores ---
def best_n(scores, n):
    valid = [s for s in scores if s is not None]
    if not valid: return None
    return sum(sorted(valid)[:n])

team_scores = []
for team in teams:
    name = team.get('name', '')
    golfers = team.get('golferNames', [])

    # Round-by-round scores for all 4 golfers
    per_round = {1: [], 2: [], 3: [], 4: []}
    golfer_details = []

    for g in golfers:
        gn = normalize(g)
        found = player_index.get(gn)

        # Last-name fallback
        if not found:
            parts = gn.split()
            if len(parts) >= 2:
                last = parts[-1]
                for key, p in player_index.items():
                    key_parts = key.split()
                    if key_parts and key_parts[-1] == last:
                        found = p
                        break

        if found:
            is_cut = (found.get('status') or '').lower() == 'cut'
            golfer_rounds = {}
            for rnum in [1, 2, 3, 4]:
                s = get_round_score(found, rnum)
                if s is None and is_cut:
                    s = worst[rnum]  # penalty
                golfer_rounds[rnum] = s
                per_round[rnum].append(s)
            golfer_details.append({'name': g, 'status': found.get('status'),
                                    'r1': golfer_rounds.get(1), 'r2': golfer_rounds.get(2),
                                    'r3': golfer_rounds.get(3), 'r4': golfer_rounds.get(4),
                                    'total': parse_score_to_par(found.get('total'))})
        else:
            print(f'  WARNING: {g} not found for team {name}')
            for rnum in [1, 2, 3, 4]:
                per_round[rnum].append(None)
            golfer_details.append({'name': g, 'status': 'Missing',
                                    'r1': None, 'r2': None, 'r3': None, 'r4': None, 'total': None})

    # Best 3 of 4 per round
    total = 0
    round_scores = {}
    for rnum in [1, 2, 3, 4]:
        b = best_n(per_round[rnum], 3)
        round_scores[f'r{rnum}'] = b
        if b is not None:
            total += b

    team_scores.append({
        'name': name,
        'totalScore': total,
        'golfers': golfer_details,
        'roundScores': round_scores,
        'ownerUid': team.get('ownerUid', '')
    })

team_scores.sort(key=lambda x: x['totalScore'])

print('\nResults:')
for i, t in enumerate(team_scores):
    rs = t['roundScores']
    print(f"  {i+1}. {t['name']}: {t['totalScore']}  (r1:{rs['r1']} r2:{rs['r2']} r3:{rs['r3']} r4:{rs['r4']})")

# --- Write back to both Firestore locations ---
now = datetime.now(timezone.utc)
db.collection('tournament_scores').document(TOURN_ID + '_latest').update({
    'teamScores': team_scores,
    'calculatedAt': firestore.SERVER_TIMESTAMP,
})
db.collection('tournaments').document(TOURN_ID).update({
    'lastCalculatedScores': team_scores,
    'lastScoreCalculation': firestore.SERVER_TIMESTAMP,
})
print(f'\nWrote {len(team_scores)} team scores to both Firestore locations.')
