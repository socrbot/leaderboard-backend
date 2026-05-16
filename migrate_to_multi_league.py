"""
migrate_to_multi_league.py

One-time migration: converts the V1 single-league data model to the
multi-league model.

What it does:
  1. Reads config/league  →  creates leagues/{newId} with the same data
  2. Adds leagueId to every tournament that doesn't already have one
  3. For every user with inLeague=True  →  sets leagueIds=[newId] (if not set)

Run against PRODUCTION only when V2 is ready to go live.
Run against STAGING to set up a test baseline.

Usage:
    GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json python migrate_to_multi_league.py
    # or point at a project explicitly:
    GCLOUD_PROJECT=alumni-golf-tournament python migrate_to_multi_league.py
"""

import os
import sys

import firebase_admin
from firebase_admin import credentials, firestore

# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

project_id = os.environ.get('GCLOUD_PROJECT') or os.environ.get('GOOGLE_CLOUD_PROJECT')
cred_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')

if cred_path:
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred, {'projectId': project_id} if project_id else {})
elif project_id:
    firebase_admin.initialize_app(options={'projectId': project_id})
else:
    print('ERROR: Set GOOGLE_APPLICATION_CREDENTIALS or GCLOUD_PROJECT')
    sys.exit(1)

db = firestore.client()

# ---------------------------------------------------------------------------
# Step 1 — copy config/league  →  leagues/{newId}
# ---------------------------------------------------------------------------

legacy_ref = db.collection('config').document('league')
legacy_doc = legacy_ref.get()

if not legacy_doc.exists:
    print('No config/league doc found — nothing to migrate.')
    sys.exit(0)

legacy = legacy_doc.to_dict()
print(f"Found legacy league: '{legacy.get('name')}'")

# Check if already migrated
existing = db.collection('leagues').where('adminUid', '==', legacy.get('adminUid', '')).limit(1).get()
existing_list = list(existing)
if existing_list:
    league_id = existing_list[0].id
    print(f'League already migrated as leagues/{league_id} — skipping creation.')
else:
    new_league_data = {
        'name': legacy.get('name', 'The Sunday Club'),
        'inviteCode': legacy.get('inviteCode', ''),
        'adminUid': legacy.get('adminUid', ''),
        'memberCount': legacy.get('memberCount', 0),
        'createdAt': legacy.get('createdAt'),
        'migratedFromLegacy': True,
    }
    _, doc_ref = db.collection('leagues').add(new_league_data)
    league_id = doc_ref.id
    print(f'Created leagues/{league_id}')

    # Copy members subcollection
    members = db.collection('config').document('league').collection('members').get()
    for m in members:
        db.collection('leagues').document(league_id).collection('members').document(m.id).set(m.to_dict())
    print(f'  Copied {len(list(members))} members')

# ---------------------------------------------------------------------------
# Step 2 — add leagueId to tournaments that don't have one
# ---------------------------------------------------------------------------

tournaments = db.collection('tournaments').get()
updated_count = 0
for t in tournaments:
    if not t.to_dict().get('leagueId'):
        db.collection('tournaments').document(t.id).update({'leagueId': league_id})
        updated_count += 1

print(f'Updated {updated_count} tournaments with leagueId={league_id}')

# ---------------------------------------------------------------------------
# Step 3 — set leagueIds on users who have inLeague=True
# ---------------------------------------------------------------------------

users = db.collection('users').where('inLeague', '==', True).get()
user_count = 0
for u in users:
    d = u.to_dict()
    if not d.get('leagueIds'):
        db.collection('users').document(u.id).update({
            'leagueIds': [league_id]
        })
        user_count += 1

print(f'Updated {user_count} users with leagueIds=[{league_id}]')
print('Migration complete.')
