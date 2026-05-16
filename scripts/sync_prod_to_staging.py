#!/usr/bin/env python3
"""
sync_prod_to_staging.py

Syncs Firestore data from the production project (alumni-golf-tournament)
to the staging project (alumni-golf-tournament-staging).

For each document in the synced collections, the script compares the
production snapshot with what exists in staging. A document is written to
staging when:
  - It does not yet exist in staging, OR
  - The production document hash differs from the staging document hash.

Collections synced:
  - tournaments
  - tournament_scores
  - global_teams

Required environment variables:
  FIREBASE_PROD_KEY     – Service-account JSON (string) for the prod project.
  FIREBASE_STAGING_KEY  – Service-account JSON (string) for the staging project.

Exit codes:
  0  – Success (with change summary printed)
  1  – Missing credentials or unexpected error
"""

import hashlib
import json
import os
import sys

import firebase_admin
from firebase_admin import credentials, firestore


COLLECTIONS = ["tournaments", "tournament_scores", "global_teams"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_cred_from_env(env_var: str) -> credentials.Certificate:
    raw = os.getenv(env_var, "").strip()
    if not raw:
        print(f"ERROR: environment variable '{env_var}' is not set or empty.", file=sys.stderr)
        sys.exit(1)
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"ERROR: '{env_var}' is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)
    return credentials.Certificate(info)


def _doc_hash(data: dict) -> str:
    """Stable SHA-256 of a Firestore document's field values."""
    serialised = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(serialised.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Main sync logic
# ---------------------------------------------------------------------------

def sync_collection(prod_db, staging_db, collection_name: str) -> dict:
    """
    Sync a single Firestore collection from prod → staging.
    Returns a summary dict: {added, updated, unchanged, errors}.
    """
    summary = {"added": 0, "updated": 0, "unchanged": 0, "errors": 0}

    prod_docs = prod_db.collection(collection_name).get()
    prod_map = {doc.id: doc.to_dict() for doc in prod_docs}

    staging_docs = staging_db.collection(collection_name).get()
    staging_map = {doc.id: doc.to_dict() for doc in staging_docs}

    print(f"\n[{collection_name}] prod={len(prod_map)} docs, staging={len(staging_map)} docs")

    for doc_id, prod_data in prod_map.items():
        try:
            prod_hash = _doc_hash(prod_data)
            staging_data = staging_map.get(doc_id)

            if staging_data is None:
                staging_db.collection(collection_name).document(doc_id).set(prod_data)
                print(f"  + ADDED   {doc_id}")
                summary["added"] += 1
            elif _doc_hash(staging_data) != prod_hash:
                staging_db.collection(collection_name).document(doc_id).set(prod_data)
                print(f"  ~ UPDATED {doc_id}")
                summary["updated"] += 1
            else:
                summary["unchanged"] += 1

        except Exception as exc:  # noqa: BLE001
            print(f"  ! ERROR   {doc_id}: {exc}", file=sys.stderr)
            summary["errors"] += 1

    return summary


def main():
    print("=== Firestore prod → staging sync ===")
    print(f"Collections: {', '.join(COLLECTIONS)}\n")

    prod_cred = _load_cred_from_env("FIREBASE_PROD_KEY")
    staging_cred = _load_cred_from_env("FIREBASE_STAGING_KEY")

    prod_app = firebase_admin.initialize_app(prod_cred, name="prod")
    staging_app = firebase_admin.initialize_app(staging_cred, name="staging")

    prod_db = firestore.client(app=prod_app)
    staging_db = firestore.client(app=staging_app)

    totals = {"added": 0, "updated": 0, "unchanged": 0, "errors": 0}

    for collection in COLLECTIONS:
        result = sync_collection(prod_db, staging_db, collection)
        for key in totals:
            totals[key] += result[key]

    print("\n=== Summary ===")
    print(f"  Added:     {totals['added']}")
    print(f"  Updated:   {totals['updated']}")
    print(f"  Unchanged: {totals['unchanged']}")
    print(f"  Errors:    {totals['errors']}")

    if totals["errors"] > 0:
        print("\nSync completed with errors.", file=sys.stderr)
        sys.exit(1)

    print("\nSync completed successfully.")


if __name__ == "__main__":
    main()
