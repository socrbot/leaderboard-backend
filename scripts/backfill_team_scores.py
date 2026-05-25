"""Backfill team scores for tournaments whose tournament_scores doc has an empty
teamScores array but a populated leaderboardData.leaderboardRows array.

This restores Production's invariant that team scores are calculated server-side
exactly once and stored in tournament_scores/{id}_latest. The V2 client no longer
recomputes scores; instead it depends on this stored data.

Usage:
    python scripts/backfill_team_scores.py --project alumni-golf-tournament-staging --dry-run
    python scripts/backfill_team_scores.py --project alumni-golf-tournament-staging --apply

If --tournament-id is provided, only that tournament is processed.
"""
from __future__ import annotations

import argparse
import os
import sys
import logging
from typing import Any, Optional

# Allow importing app.calculate_team_scores by adding repo root to path.
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(THIS_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import firebase_admin  # noqa: E402
from firebase_admin import credentials, firestore  # noqa: E402

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger('backfill_team_scores')


def _init_firestore(project: str, credentials_path: Optional[str]):
    """Initialize Firebase via the same path app.py uses, then return the client.

    We set FIREBASE_SERVICE_ACCOUNT_KEY_PATH and GOOGLE_CLOUD_PROJECT *before* importing
    app.py so that app.py performs the single initialize_app() call. Importing app.py
    afterwards gives us access to calculate_team_scores without re-initializing.
    """
    if credentials_path:
        os.environ['FIREBASE_SERVICE_ACCOUNT_KEY_PATH'] = credentials_path
    os.environ.setdefault('GOOGLE_CLOUD_PROJECT', project)
    # Importing app triggers firebase_admin.initialize_app() inside app.py.
    import app as backend_app  # noqa: F401  (side-effect import)
    if backend_app.db is None:
        raise RuntimeError('app.py failed to initialize Firestore client')
    return backend_app.db


def _calculate_team_scores(players, team_assignments, par):
    from app import calculate_team_scores  # type: ignore
    return calculate_team_scores(players, team_assignments, par)


def _firestore_safe(value):
    """Coerce dict keys to strings recursively so values are Firestore-encodable."""
    if isinstance(value, dict):
        return {str(k): _firestore_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_firestore_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_firestore_safe(v) for v in value]
    return value


def _process_tournament(db, tournament_id: str, apply: bool) -> dict:
    result = {
        'tournamentId': tournament_id,
        'status': 'skipped',
        'reason': '',
    }

    score_ref = db.collection('tournament_scores').document(f'{tournament_id}_latest')
    score_doc = score_ref.get()
    if not score_doc.exists:
        result['reason'] = 'no_score_doc'
        return result

    score_data = score_doc.to_dict() or {}
    existing_team_scores = score_data.get('teamScores') or []
    leaderboard_data = score_data.get('leaderboardData') or {}
    leaderboard_rows = leaderboard_data.get('leaderboardRows') or []

    if existing_team_scores:
        result['reason'] = 'team_scores_already_present'
        return result

    if not leaderboard_rows:
        result['reason'] = 'no_legacy_rows'
        return result

    tournament_ref = db.collection('tournaments').document(tournament_id)
    tournament_doc = tournament_ref.get()
    if not tournament_doc.exists:
        result['reason'] = 'tournament_doc_missing'
        return result

    tournament_data = tournament_doc.to_dict() or {}
    team_assignments = tournament_data.get('teams') or []
    if not team_assignments:
        result['reason'] = 'no_team_assignments'
        return result
    par = tournament_data.get('par', 72)

    try:
        team_scores = _calculate_team_scores(leaderboard_rows, team_assignments, par)
    except Exception as exc:  # noqa: BLE001
        log.exception('calculate_team_scores failed for %s', tournament_id)
        result['status'] = 'error'
        result['reason'] = f'calc_failed:{exc}'
        return result

    if not team_scores:
        result['reason'] = 'calc_returned_empty'
        return result

    result['teamsComputed'] = len(team_scores)
    if not apply:
        result['status'] = 'would_write'
        return result

    score_ref.update({
        'teamScores': _firestore_safe(team_scores),
        'backfilledAt': firestore.SERVER_TIMESTAMP,
        'backfillSource': 'scripts/backfill_team_scores.py',
    })
    tournament_ref.update({
        'lastCalculatedScores': _firestore_safe(team_scores),
        'lastScoreCalculation': firestore.SERVER_TIMESTAMP,
    })
    result['status'] = 'written'
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, help='GCP project id (e.g. alumni-golf-tournament-staging)')
    parser.add_argument('--credentials', default=None, help='Path to service-account JSON. If omitted, ADC is used.')
    parser.add_argument('--tournament-id', default=None, help='Only backfill this tournament id.')
    parser.add_argument('--apply', action='store_true', help='Write changes. Default is dry-run.')
    parser.add_argument('--dry-run', action='store_true', help='Explicit dry-run (default).')
    args = parser.parse_args()

    if args.apply and args.dry_run:
        log.error('--apply and --dry-run are mutually exclusive')
        return 2

    apply = bool(args.apply)
    db = _init_firestore(args.project, args.credentials)

    if args.tournament_id:
        ids = [args.tournament_id]
    else:
        ids = [doc.id for doc in db.collection('tournaments').stream()]
        log.info('Scanning %d tournaments', len(ids))

    summary = {'written': 0, 'would_write': 0, 'skipped': 0, 'error': 0}
    for tid in ids:
        outcome = _process_tournament(db, tid, apply=apply)
        log.info('%s -> %s (%s)', tid, outcome['status'], outcome.get('reason') or outcome.get('teamsComputed'))
        summary[outcome['status']] = summary.get(outcome['status'], 0) + 1

    log.info('Done. Summary: %s', summary)
    return 0


if __name__ == '__main__':
    sys.exit(main())
