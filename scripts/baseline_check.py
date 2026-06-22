#!/usr/bin/env python3
"""
baseline_check.py
Read-only pre-migration baseline snapshot of production Firestore.
Usage: GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json python scripts/baseline_check.py
"""
import os
import firebase_admin
from firebase_admin import credentials, firestore

key = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
cred = credentials.Certificate(key)
firebase_admin.initialize_app(cred)
db = firestore.client()

print("=== PRODUCTION FIRESTORE BASELINE (pre-migration) ===")

for col in ["users", "tournaments", "global_teams", "tournament_scores", "leagues"]:
    count = len(list(db.collection(col).get()))
    print(f"  {col}: {count} docs")

cfg = db.collection("config").document("league").get()
status = "EXISTS" if cfg.exists else "NOT FOUND"
print(f"  config/league: {status}")
if cfg.exists:
    d = cfg.to_dict()
    print(f"    name={d.get('name')}, adminUid={d.get('adminUid')}, memberCount={d.get('memberCount')}")
    members = list(db.collection("config").document("league").collection("members").get())
    print(f"    config/league/members: {len(members)} docs")

tourns = list(db.collection("tournaments").get())
with_league = sum(1 for t in tourns if t.to_dict().get("leagueId"))
print(f"  tournaments with leagueId: {with_league}/{len(tourns)}")

users_docs = list(db.collection("users").get())
with_ids = sum(1 for u in users_docs if u.to_dict().get("leagueIds"))
in_league = sum(1 for u in users_docs if u.to_dict().get("inLeague"))
print(f"  users with leagueIds[]: {with_ids}/{len(users_docs)}")
print(f"  users with inLeague=True: {in_league}/{len(users_docs)}")

teams = list(db.collection("global_teams").get())
with_year = sum(1 for t in teams if t.to_dict().get("year"))
print(f"  global_teams with year: {with_year}/{len(teams)}")
print("=== END BASELINE ===")
