#!/usr/bin/env python3
"""
bootstrap_staging_admin.py

One-time staging utility to bootstrap an existing Firebase Auth user as:
1) Platform admin (users/{uid}.role = "admin")
2) Member of selected leagues (leagues/{leagueId}/members/{uid})
3) Optional owner of selected leagues (leagues/{leagueId}.adminUid = uid)

Safety defaults:
- Dry-run by default (no writes).
- Requires --apply to persist changes.

Required env var:
- FIREBASE_STAGING_KEY: service-account JSON for alumni-golf-tournament-staging.

Example:
  python scripts/bootstrap_staging_admin.py \
    --admin-uid <UID> \
    --league-ids <LEAGUE_ID_1>,<LEAGUE_ID_2> \
    --email <EMAIL> \
    --display-name "<NAME>" \
    --team-name "<TEAM_NAME>" \
    --make-owner \
    --apply
"""

import argparse
import json
import os
import sys
from typing import Dict, List, Tuple

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
    parser = argparse.ArgumentParser(description="Bootstrap one staging admin user into leagues.")
    parser.add_argument("--admin-uid", required=True, help="Firebase Auth UID of the staging admin user")
    parser.add_argument(
        "--league-ids",
        default="",
        help="Comma-separated league IDs. If omitted, uses all leagues where adminUid already matches this UID.",
    )
    parser.add_argument("--email", default="", help="Email to store in users/members docs")
    parser.add_argument("--display-name", default="", help="Display name to store in users/members docs")
    parser.add_argument("--team-name", default="", help="Team name to store in users/members docs")
    parser.add_argument(
        "--participates-in-annual",
        dest="participates_in_annual",
        action="store_true",
        help="Set participatesInAnnual=true on member docs.",
    )
    parser.add_argument(
        "--no-participates-in-annual",
        dest="participates_in_annual",
        action="store_false",
        help="Set participatesInAnnual=false on member docs.",
    )
    parser.set_defaults(participates_in_annual=True)
    parser.add_argument(
        "--make-owner",
        action="store_true",
        help="Also set leagues/{leagueId}.adminUid to this admin UID.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist writes. Without this flag, script runs in dry-run mode.",
    )
    return parser.parse_args()


def resolve_league_ids(db, admin_uid: str, raw_league_ids: str) -> List[str]:
    explicit_ids = [x.strip() for x in raw_league_ids.split(",") if x.strip()]
    if explicit_ids:
        return sorted(set(explicit_ids))

    docs = db.collection("leagues").where("adminUid", "==", admin_uid).get()
    return sorted([doc.id for doc in docs])


def get_existing_user(db, admin_uid: str) -> Dict:
    snap = db.collection("users").document(admin_uid).get()
    return snap.to_dict() if snap.exists else {}


def build_user_payload(existing: Dict, admin_uid: str, league_ids: List[str], args: argparse.Namespace) -> Dict:
    existing_league_ids = existing.get("leagueIds", []) or []
    merged_league_ids = sorted(set(existing_league_ids + league_ids))

    payload = {
        "uid": admin_uid,
        "role": "admin",
        "inLeague": len(merged_league_ids) > 0,
        "leagueIds": merged_league_ids,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }

    email = args.email or existing.get("email", "")
    display_name = args.display_name or existing.get("displayName", "")

    if email:
        payload["email"] = email
    if display_name:
        payload["displayName"] = display_name

    # Keep one global team identity if available.
    team_name = args.team_name or existing.get("teamName", "")
    if team_name:
        payload["teamName"] = team_name

    if not existing.get("createdAt"):
        payload["createdAt"] = firestore.SERVER_TIMESTAMP

    return payload


def ensure_member_doc(
    db,
    league_id: str,
    admin_uid: str,
    email: str,
    display_name: str,
    team_name: str,
    participates_in_annual: bool,
    apply: bool,
) -> Tuple[bool, str]:
    league_ref = db.collection("leagues").document(league_id)
    league_snap = league_ref.get()
    if not league_snap.exists:
        return False, f"League not found: {league_id}"

    member_ref = league_ref.collection("members").document(admin_uid)
    member_snap = member_ref.get()
    member_exists = member_snap.exists

    member_payload = {
        "uid": admin_uid,
        "email": email,
        "displayName": display_name,
        "participatesInAnnual": bool(participates_in_annual),
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }

    if team_name:
        member_payload["teamName"] = team_name

    if not member_exists:
        member_payload["joinedAt"] = firestore.SERVER_TIMESTAMP

    if apply:
        member_ref.set(member_payload, merge=True)
        if not member_exists:
            league_ref.update({"memberCount": firestore.Increment(1)})

    if member_exists:
        return True, f"Member exists -> updated fields in league {league_id}"
    return True, f"Member created in league {league_id}"


def maybe_set_owner(db, league_id: str, admin_uid: str, apply: bool) -> str:
    league_ref = db.collection("leagues").document(league_id)
    snap = league_ref.get()
    if not snap.exists:
        return f"Skipped owner update (league missing): {league_id}"

    current_owner = (snap.to_dict() or {}).get("adminUid", "")
    if current_owner == admin_uid:
        return f"Owner unchanged for league {league_id}"

    if apply:
        league_ref.set({"adminUid": admin_uid, "updatedAt": firestore.SERVER_TIMESTAMP}, merge=True)
    return f"Owner set to {admin_uid} for league {league_id}"


def main() -> None:
    args = parse_args()

    cred = load_staging_credentials()
    app = firebase_admin.initialize_app(cred, name="staging-bootstrap-admin")
    db = firestore.client(app=app)

    league_ids = resolve_league_ids(db, args.admin_uid, args.league_ids)

    print("=== Staging Admin Bootstrap ===")
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}")
    print(f"Admin UID: {args.admin_uid}")
    print(f"League count: {len(league_ids)}")
    if league_ids:
        print("Leagues:")
        for lid in league_ids:
            print(f"  - {lid}")
    else:
        print("WARNING: No leagues resolved. User doc will still be updated to role=admin.")

    existing_user = get_existing_user(db, args.admin_uid)
    user_payload = build_user_payload(existing_user, args.admin_uid, league_ids, args)

    print("\nUser doc changes (users/{uid}):")
    print(f"  role: {user_payload.get('role')}")
    print(f"  inLeague: {user_payload.get('inLeague')}")
    print(f"  leagueIds: {user_payload.get('leagueIds')}")

    if args.apply:
        db.collection("users").document(args.admin_uid).set(user_payload, merge=True)

    member_results = []
    member_errors = []

    for league_id in league_ids:
        ok, message = ensure_member_doc(
            db=db,
            league_id=league_id,
            admin_uid=args.admin_uid,
            email=args.email or user_payload.get("email", ""),
            display_name=args.display_name or user_payload.get("displayName", ""),
            team_name=args.team_name or user_payload.get("teamName", ""),
            participates_in_annual=args.participates_in_annual,
            apply=args.apply,
        )
        if ok:
            member_results.append(message)
        else:
            member_errors.append(message)

    owner_results = []
    if args.make_owner:
        for league_id in league_ids:
            owner_results.append(maybe_set_owner(db, league_id, args.admin_uid, args.apply))

    print("\nMembership updates:")
    if member_results:
        for row in member_results:
            print(f"  - {row}")
    else:
        print("  - None")

    if args.make_owner:
        print("\nOwner updates:")
        for row in owner_results:
            print(f"  - {row}")

    if member_errors:
        print("\nErrors:", file=sys.stderr)
        for err in member_errors:
            print(f"  - {err}", file=sys.stderr)

    print("\nDone.")
    if not args.apply:
        print("Dry-run only. Re-run with --apply to persist changes.")


if __name__ == "__main__":
    main()
