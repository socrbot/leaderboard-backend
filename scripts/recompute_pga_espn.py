"""Recompute 2026 PGA Championship team scores from ESPN verified results."""
import firebase_admin
from firebase_admin import credentials, firestore
import os
from datetime import datetime, timezone

os.environ['GOOGLE_CLOUD_PROJECT'] = 'alumni-golf-tournament'
cred = credentials.ApplicationDefault()
firebase_admin.initialize_app(cred, {'projectId': 'alumni-golf-tournament'})
db = firestore.client()

TOURN_ID = '1yRK1FAq9AqKQp3goX91'
PAR = 70

# ESPN verified final results: name -> (r1, r2, r3, r4) strokes, or None if CUT
# CUT players only have r1, r2
ESPN = {
    'Aaron Rai':          (70, 69, 67, 65),
    'Jon Rahm':           (69, 70, 67, 68),
    'Justin Thomas':      (69, 69, 72, 65),
    'Ludvig Aberg':       (72, 66, 68, 69),   # Åberg, finished T4 -5
    'Xander Schauffele':  (68, 73, 66, 69),
    'Rory McIlroy':       (74, 67, 66, 69),   # T7 -4, NOT cut
    'Justin Rose':        (70, 73, 65, 69),
    'Chris Gotterup':     (72, 65, 71, 69),
    'Patrick Reed':       (68, 72, 67, 70),
    'Matt Fitzpatrick':   (70, 72, 71, 65),
    'Scottie Scheffler':  (67, 71, 71, 69),
    'Ben Griffin':        (71, 70, 67, 70),
    'Robert MacIntyre':   (71, 70, 67, 70),
    'Jordan Spieth':      (69, 72, 70, 68),
    'Harris English':     (71, 67, 71, 70),
    'Joaquin Niemann':    (69, 73, 66, 71),
    'Min Woo Lee':        (67, 70, 71, 71),
    'Maverick McNealy':   (69, 67, 71, 72),
    'Cameron Young':      (71, 67, 72, 70),
    'Hideki Matsuyama':   (70, 67, 71, 72),
    'Sam Burns':          (70, 72, 67, 71),
    'Alexander Noren':    (71, 73, 70, 66),
    'Patrick Cantlay':    (70, 69, 74, 68),
    'Si Woo Kim':         (71, 67, 72, 71),
    'Collin Morikawa':    (69, 72, 74, 68),
    'Corey Conners':      (68, 73, 72, 70),
    'Brooks Koepka':      (69, 72, 68, 74),
    'Rickie Fowler':      (70, 71, 68, 75),
    'Jason Day':          (69, 70, 75, 72),
    'Shane Lowry':        (68, 76, 70, 68),
    'Nicolai Hojgaard':   (69, 75, 66, 72),   # T44 +2, made cut
    'Kristoffer Reitan':  (71, 72, 65, 74),   # T44 +2
    # CUT players (r3=r4=None)
    'Russell Henley':     (72, 73, None, None),
    'Tyrrell Hatton':     (72, 74, None, None),
    'Akshay Bhatia':      (71, 74, None, None),
    'Tommy Fleetwood':    (72, 73, None, None),
    'Viktor Hovland':     (74, 72, None, None),
    'Bryson DeChambeau':  (76, 71, None, None),
    'Gary Woodland':      (72, 74, None, None),
    'Adam Scott':         (72, 76, None, None),
    'Keegan Bradley':     (74, 72, None, None),
    'Sepp Straka':        (73, 73, None, None),
    # Sungjae Im made the cut per stored Firestore data (74-68-71-75, +8)
    'Sungjae Im':         (74, 68, 71, 75),
    'Sung-Jae Im':        (74, 68, 71, 75),
    # J.J. Spaun missed the cut per stored Firestore data (77-71)
    'J.J. Spaun':         (77, 71, None, None),
    'JJ Spaun':           (77, 71, None, None),
}

def stp(strokes):
    """Strokes to score-to-par."""
    if strokes is None: return None
    return strokes - PAR

# Build per-round score lookup
def get_r(name, rnum):
    """Return score-to-par for player in round, or None if not available."""
    data = ESPN.get(name)
    if data is None: return None
    s = data[rnum - 1]
    return stp(s)

# Compute worst non-CUT score per round for cut penalty
def worst_noncut_round(rnum):
    worst = None
    for name, rounds in ESPN.items():
        if rounds[2] is not None:  # made the cut
            s = rounds[rnum - 1]
            if s is not None:
                spar = s - PAR
                if worst is None or spar > worst:
                    worst = spar
    return (worst + 1) if worst is not None else 8  # fallback

worst = {r: worst_noncut_round(r) for r in [1, 2, 3, 4]}
print(f'Cut penalties per round: {worst}')

# Load teams
tourn = db.collection('tournaments').document(TOURN_ID).get().to_dict()
teams = tourn.get('teams', [])
print(f'Teams: {len(teams)}')

def best_n(scores, n):
    valid = [s for s in scores if s is not None]
    if not valid: return None
    return sum(sorted(valid)[:n])

team_scores = []
for team in teams:
    name = team.get('name', '')
    golfers = team.get('golferNames', [])

    per_round = {1: [], 2: [], 3: [], 4: []}
    golfer_details = []

    for g in golfers:
        is_cut = ESPN.get(g, (1,1,None,None))[2] is None
        not_in_field = g not in ESPN

        r_scores = {}
        for rnum in [1, 2, 3, 4]:
            s = get_r(g, rnum)
            if s is None and not not_in_field:
                s = worst[rnum]  # cut penalty
            r_scores[rnum] = s
            per_round[rnum].append(s)

        status = 'Missing' if not_in_field else ('CUT' if is_cut else 'complete')
        total = sum(v for v in r_scores.values() if v is not None and v != worst[3] and v != worst[4]) if not is_cut else None
        golfer_details.append({
            'name': g, 'status': status,
            'r1': r_scores[1], 'r2': r_scores[2],
            'r3': r_scores[3], 'r4': r_scores[4],
        })

    total_score = 0
    round_scores = {}
    for rnum in [1, 2, 3, 4]:
        b = best_n(per_round[rnum], 3)
        round_scores[f'r{rnum}'] = b
        if b is not None:
            total_score += b

    team_scores.append({
        'teamName': name,
        'name': name,
        'totalScore': total_score,
        'golfers': golfer_details,
        'roundScores': round_scores,
        'ownerUid': team.get('ownerUid', '')
    })

team_scores.sort(key=lambda x: x['totalScore'])

print('\nFinal Results (ESPN verified):')
for i, t in enumerate(team_scores):
    rs = t['roundScores']
    print(f"  {i+1}. {t['name']}: {t['totalScore']}  "
          f"(r1:{rs['r1']} r2:{rs['r2']} r3:{rs['r3']} r4:{rs['r4']})")
    for g in t['golfers']:
        print(f"      {g['name']}: {g['status']} r1:{g['r1']} r2:{g['r2']} r3:{g['r3']} r4:{g['r4']}")

# Write to Firestore
db.collection('tournament_scores').document(TOURN_ID + '_latest').update({
    'teamScores': team_scores,
    'calculatedAt': firestore.SERVER_TIMESTAMP,
})
db.collection('tournaments').document(TOURN_ID).update({
    'lastCalculatedScores': team_scores,
    'lastScoreCalculation': firestore.SERVER_TIMESTAMP,
})
print(f'\nWrote {len(team_scores)} team scores to Firestore.')
