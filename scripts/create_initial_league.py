#!/usr/bin/env python3
"""
create_initial_league.py

One-time script for production environments where config/league does NOT exist.
Creates a leagues/{id} document from scratch and stamps all un-scoped tournaments
with the new leagueId.

Run AFTER taking a Firestore backup.

Required env vars:
  GOOGLE_APPLICATION_CREDENTIALS  – path to service-account JSON
  LEAGUE_ADMIN_UID                 – Firebase Auth UID of the league admin/owner
  LEAGUE_NAME                      – display name for the league (default: "The Sunday Club")

Exit codes:
  0 – success
  1 – missing configuration
"""

import os
import sys
from datetime import datetime, timezone

import firebase_admin
from firebase_admin import credentials, firestore

# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
admin_uid = os.environ.get("LEAGUE_ADMIN_UID", "").strip()
league_name = os.environ.get("LEAGUE_NAME", "The Sunday Club").strip()

if not cred_path:
    print("ERROR: GOOGLE_APPLICATION_CREDENTIALS not set", file=sys.stderr)
    sys.exit(1)

if not admin_uid:
    print("ERROR: LEAGUE_ADMIN_UID not set. Set it to the Firebase Auth UID of the admin.", file=sys.stderr)
    sys.exit(1)

cred = credentials.Certificate(cred_path)
firebase_admin.initialize_app(cred)
db = firestore.client()

# ---------------------------------------------------------------------------
# Guard: abort if a league already exists for this admin
# ---------------------------------------------------------------------------

existing = list(db.collection("leagues").where("adminUid", "==", admin_uid).limit(1).get())
if existing:
    league_id = existing[0].id
    print(f"League already exists for adminUid={admin_uid}: leagues/{league_id}")
    print("Nothing to create — checking tournaments for missing leagueId...")
else:
    # ---------------------------------------------------------------------------
    # Step 1 — Create leagues/{id}
    # ---------------------------------------------------------------------------
    league_data = {
        "name": league_name,
        "adminUid": admin_uid,
        "memberCount": 0,
        "inviteCode": "",   # Set via admin UI or regenerate endpoint after creation
        "createdAt": datetime.now(timezone.utc),
        "migratedFromLegacy": False,
        "schemaVersion": 2,
    }
    _, doc_ref = db.collection("leagues").add(league_data)
    league_id = doc_ref.id
    print(f"Created leagues/{league_id} (name='{league_name}', adminUid={admin_uid})")

    # ---------------------------------------------------------------------------
    # Step 2 — Add admin to leagues/{id}/members
    # ---------------------------------------------------------------------------
    db.collection("leagues").document(league_id).collection("members").document(admin_uid).set({
        "uid": admin_uid,
        "role": "admin",
        "joinedAt": datetime.now(timezone.utc),
    })
    print(f"  Added admin {admin_uid} to leagues/{league_id}/members")

    # ---------------------------------------------------------------------------
    # Step 3 — Backfill admin user doc with leagueIds[]
    # ---------------------------------------------------------------------------
    user_ref = db.collection("users").document(admin_uid)
    user_doc = user_ref.get()
    if user_doc.exists:
        existing_ids = user_doc.to_dict().get("leagueIds") or []
        if league_id not in existing_ids:
            user_ref.update({"leagueIds": existing_ids + [league_id]})
            print(f"  Updated users/{admin_uid}.leagueIds = {existing_ids + [league_id]}")
    else:
        print(f"  WARNING: users/{admin_uid} doc not found. User will get leagueIds on first login.")

# ---------------------------------------------------------------------------
# Step 4 — Stamp leagueId on all tournaments that don't have one
# ---------------------------------------------------------------------------

tournaments = db.collection("tournaments").get()
updated_count = 0
for t in tournaments:
    if not t.to_dict().get("leagueId"):
        db.collection("tournaments").document(t.id).update({
            "leagueId": league_id,
            "schemaVersion": 2,
        })
        updated_count += 1
        print(f"  Stamped leagueId={league_id} on tournament/{t.id}")

print(f"\nUpdated {updated_count} tournaments with leagueId={league_id}")
print("Done. Next step: set inviteCode via admin UI or POST /api/leagues/<id>/regenerate_code")
