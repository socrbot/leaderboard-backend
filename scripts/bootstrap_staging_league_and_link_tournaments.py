#!/usr/bin/env python3
"""
bootstrap_staging_league_and_link_tournaments.py

One-time staging migration helper that can:
1) Create a new league (or use an existing league)
2) Set an admin user as platform admin + league member
3) Backfill tournaments that are missing leagueId to that league

Safety defaults:
- Dry-run by default. Use --apply to persist writes.

Required env var:
- FIREBASE_STAGING_KEY: service-account JSON for alumni-golf-tournament-staging.

Example (recommended path if migrated tournaments have no leagueId):
  python scripts/bootstrap_staging_league_and_link_tournaments.py \
    --admin-uid R2s8mPqmspMbe0BIY3VZ2XOPfbE3 \
    --create-league-name "Staging Main League" \
    --email "you@example.com" \
    --display-name "Your Name" \
    --team-name "Commissioner" \
    --apply
"""

import argparse
import json
import os
import random
import string
import sys
from typing import Dict, List, Optional, Tuple

import firebase_admin
from firebase_admin import credentials, firestore


EXPECTED_PROJECT_ID = "alumni-golf-tournament-staging"


def load_staging_credentials() -> credentials.Certificate:
    raw = os.getenv("FIREBASE_STAGING_KEY", "").strip()
    if not raw:
        print("ERROR: FIREBASE_STAGING_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"ERROR: FIREBASE_STAGING_KEY is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    project_id = payload.get("project_id", "")
    if project_id and project_id != EXPECTED_PROJECT_ID:
        print(
            f"ERROR: FIREBASE_STAGING_KEY project_id is '{project_id}', expected '{EXPECTED_PROJECT_ID}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    return credentials.Certificate(payload)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create/use a staging league and link unscoped tournaments."
    )
    parser.add_argument("--admin-uid", required=True, help="Firebase Auth UID for staging admin")
    parser.add_argument("--league-id", default="", help="Use an existing league ID instead of creating one")
    parser.add_argument(
        "--create-league-name",
        default="",
        help="Create a new league with this name if --league-id is not provided",
    )
    parser.add_argument("--invite-code", default="", help="Optional invite code when creating a new league")
    parser.add_argument("--email", default="", help="Email for users/members documents")
    parser.add_argument("--display-name", default="", help="Display name for users/members documents")
    parser.add_argument("--team-name", default="", help="Team name for users/members documents")
    parser.add_argument(
        "--no-participates-in-annual",
        dest="participates_in_annual",
        action="store_false",
        help="Set participatesInAnnual=false in league member document",
    )
    parser.set_defaults(participates_in_annual=True)
    parser.add_argument(
        "--link-all-tournaments",
        action="store_true",
        help="Link all tournaments to the league, not only missing/blank leagueId.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist changes. Without this flag, runs as dry-run.",
    )
    return parser.parse_args()


def make_invite_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(6))


def resolve_or_create_league(db, args: argparse.Namespace) -> Tuple[Optional[str], List[str]]:
    notes: List[str] = []
    provided_league_id = (args.league_id or "").strip()

    if provided_league_id:
        snap = db.collection("leagues").document(provided_league_id).get()
        if not snap.exists:
            raise ValueError(f"League not found for --league-id: {provided_league_id}")
        notes.append(f"Using existing league: {provided_league_id}")
        return provided_league_id, notes

    league_name = (args.create_league_name or "").strip()
    if not league_name:
        raise ValueError("Provide either --league-id or --create-league-name")

    invite_code = (args.invite_code or "").strip().upper() or make_invite_code()
    league_payload = {
        "name": league_name,
        "inviteCode": invite_code,
        "adminUid": args.admin_uid,
        "memberCount": 1,
        "createdAt": firestore.SERVER_TIMESTAMP,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }

    if args.apply:
        doc_ref = db.collection("leagues").document()
        doc_ref.set(league_payload)
        league_id = doc_ref.id
    else:
        league_id = "DRY_RUN_NEW_LEAGUE_ID"

    notes.append(f"Will create league '{league_name}' with inviteCode '{invite_code}'")
    notes.append(f"Resolved target leagueId: {league_id}")
    return league_id, notes


def ensure_user_doc(db, args: argparse.Namespace, league_id: str) -> Dict:
    user_ref = db.collection("users").document(args.admin_uid)
    user_snap = user_ref.get()
    existing = user_snap.to_dict() if user_snap.exists else {}

    existing_leagues = existing.get("leagueIds", []) or []
    merged_leagues = sorted(set(existing_leagues + [league_id]))

    payload: Dict = {
        "uid": args.admin_uid,
        "role": "admin",
        "inLeague": True,
        "leagueIds": merged_leagues,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }

    email = args.email or existing.get("email", "")
    display_name = args.display_name or existing.get("displayName", "")
    team_name = args.team_name or existing.get("teamName", "")

    if email:
        payload["email"] = email
    if display_name:
        payload["displayName"] = display_name
    if team_name:
        payload["teamName"] = team_name

    if not existing.get("createdAt"):
        payload["createdAt"] = firestore.SERVER_TIMESTAMP

    if args.apply:
        user_ref.set(payload, merge=True)

    return payload


def ensure_member_doc(db, args: argparse.Namespace, league_id: str, user_payload: Dict) -> str:
    league_ref = db.collection("leagues").document(league_id)
    member_ref = league_ref.collection("members").document(args.admin_uid)
    member_snap = member_ref.get()
    member_exists = member_snap.exists

    payload = {
        "uid": args.admin_uid,
        "email": args.email or user_payload.get("email", ""),
        "displayName": args.display_name or user_payload.get("displayName", ""),
        "participatesInAnnual": bool(args.participates_in_annual),
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }

    team_name = args.team_name or user_payload.get("teamName", "")
    if team_name:
        payload["teamName"] = team_name

    if not member_exists:
        payload["joinedAt"] = firestore.SERVER_TIMESTAMP

    if args.apply:
        member_ref.set(payload, merge=True)
        if not member_exists:
            league_ref.update({"memberCount": firestore.Increment(1)})

    return "updated existing member" if member_exists else "created member"


def tournament_needs_link(data: Dict, link_all: bool) -> bool:
    if link_all:
        return True
    raw = data.get("leagueId")
    if raw is None:
        return True
    if isinstance(raw, str) and not raw.strip():
        return True
    return False


def backfill_tournaments(db, league_id: str, link_all: bool, apply: bool) -> Tuple[int, int, List[str]]:
    docs = db.collection("tournaments").get()
    scanned = 0
    updated = 0
    touched_ids: List[str] = []

    for doc in docs:
        scanned += 1
        data = doc.to_dict() or {}
        if not tournament_needs_link(data, link_all):
            continue

        touched_ids.append(doc.id)
        updated += 1

        if apply:
            db.collection("tournaments").document(doc.id).set(
                {"leagueId": league_id, "updatedAt": firestore.SERVER_TIMESTAMP},
                merge=True,
            )

    return scanned, updated, touched_ids


def main() -> None:
    args = parse_args()

    cred = load_staging_credentials()
    app = firebase_admin.initialize_app(cred, name="staging-league-linker")
    db = firestore.client(app=app)

    print("=== Staging League + Tournament Link Bootstrap ===")
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}")
    print(f"Admin UID: {args.admin_uid}")

    try:
        league_id, league_notes = resolve_or_create_league(db, args)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print("\nLeague resolution:")
    for note in league_notes:
        print(f"  - {note}")

    user_payload = ensure_user_doc(db, args, league_id)
    member_result = ensure_member_doc(db, args, league_id, user_payload)

    scanned, updated, touched_ids = backfill_tournaments(
        db=db,
        league_id=league_id,
        link_all=bool(args.link_all_tournaments),
        apply=bool(args.apply),
    )

    print("\nUser doc update:")
    print(f"  - role: {user_payload.get('role')}")
    print(f"  - inLeague: {user_payload.get('inLeague')}")
    print(f"  - leagueIds: {user_payload.get('leagueIds')}")

    print("\nMember update:")
    print(f"  - {member_result}")

    print("\nTournament backfill:")
    print(f"  - scanned: {scanned}")
    print(f"  - to update: {updated}")
    if touched_ids:
        preview = touched_ids[:20]
        print(f"  - sample IDs: {preview}")
        if len(touched_ids) > 20:
            print(f"  - ... and {len(touched_ids) - 20} more")

    if not args.apply:
        print("\nDry-run only. Re-run with --apply to persist changes.")

    print("\nDone.")


if __name__ == "__main__":
    main()
