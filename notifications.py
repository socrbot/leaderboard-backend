"""FCM push notifications for draft workflow.

Tokens are stored at users/{uid}/fcmTokens/{token} with doc body:
  { platform: 'android'|'ios'|'web', createdAt }

Stale tokens (NotRegistered / Unregistered / invalid-argument) are deleted
automatically when a send fails.
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

from firebase_admin import messaging

logger = logging.getLogger(__name__)


def _read_user_tokens(db, uid: str) -> list[str]:
    if not uid:
        return []
    try:
        snaps = db.collection('users').document(uid).collection('fcmTokens').stream()
        return [s.id for s in snaps]
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("Failed to read fcmTokens for %s: %s", uid, e)
        return []


def _delete_stale_token(db, uid: str, token: str) -> None:
    try:
        db.collection('users').document(uid).collection('fcmTokens').document(token).delete()
    except Exception as e:  # pragma: no cover
        logger.warning("Failed to delete stale token for %s: %s", uid, e)


_STALE_ERROR_CODES = {
    'registration-token-not-registered',
    'invalid-argument',
    'invalid-registration-token',
    'messaging/registration-token-not-registered',
    'messaging/invalid-argument',
    'messaging/invalid-registration-token',
}


def send_to_user(
    db,
    uid: str,
    title: str,
    body: str,
    data: Optional[dict] = None,
) -> int:
    """Send a notification to every device registered for uid. Returns success count."""
    tokens = _read_user_tokens(db, uid)
    if not tokens:
        return 0

    # Data payload values must be strings.
    str_data = {k: str(v) for k, v in (data or {}).items()}

    message = messaging.MulticastMessage(
        tokens=tokens,
        notification=messaging.Notification(title=title, body=body),
        data=str_data,
        android=messaging.AndroidConfig(
            priority='high',
            notification=messaging.AndroidNotification(
                channel_id='draft_updates',
                sound='default',
            ),
        ),
    )

    try:
        resp = messaging.send_each_for_multicast(message)
    except Exception as e:  # pragma: no cover
        logger.error("FCM send failed for %s: %s", uid, e)
        return 0

    for token, result in zip(tokens, resp.responses):
        if not result.success and result.exception is not None:
            code = getattr(result.exception, 'code', '') or ''
            if code in _STALE_ERROR_CODES:
                _delete_stale_token(db, uid, token)
            else:
                logger.warning("FCM error for %s token=%s: %s", uid, token[:12], result.exception)

    return resp.success_count


def send_to_users(
    db,
    uids: Iterable[str],
    title: str,
    body: str,
    data: Optional[dict] = None,
) -> int:
    total = 0
    seen: set[str] = set()
    for uid in uids:
        if not uid or uid in seen:
            continue
        seen.add(uid)
        total += send_to_user(db, uid, title, body, data)
    return total


# ----- Draft event helpers --------------------------------------------------

def _team_owner_uids(tournament_data: dict) -> list[str]:
    return [t.get('ownerUid') for t in (tournament_data.get('teams') or []) if t.get('ownerUid')]


def _compute_current_pick_owner(tournament_data: dict) -> Optional[str]:
    """Return ownerUid of whoever is next to pick, or None if draft is done."""
    teams = tournament_data.get('teams') or []
    draft_picks = tournament_data.get('draftPicks') or []
    num_teams = len(teams)
    if num_teams == 0:
        return None
    total_picks = 4 * num_teams
    if len(draft_picks) >= total_picks:
        return None
    next_pick_number = len(draft_picks) + 1
    round_idx = (next_pick_number - 1) // num_teams
    pick_in_round = (next_pick_number - 1) % num_teams
    sorted_teams = sorted(teams, key=lambda t: t.get('draftOrder', 999))
    if round_idx % 2 == 0:
        current = sorted_teams[pick_in_round]
    else:
        current = sorted_teams[num_teams - 1 - pick_in_round]
    return current.get('ownerUid')


def notify_draft_started(db, tournament_id: str, tournament_data: dict) -> None:
    name = tournament_data.get('name') or 'your tournament'
    data = {'type': 'draft_started', 'tournamentId': tournament_id}
    owners = _team_owner_uids(tournament_data)
    send_to_users(db, owners, 'Draft started', name, data)
    # Also notify the first picker.
    first = _compute_current_pick_owner(tournament_data)
    if first:
        send_to_user(db, first, "You're on the clock", name, {**data, 'type': 'your_turn'})


def notify_your_turn(db, tournament_id: str, tournament_data: dict) -> None:
    owner = _compute_current_pick_owner(tournament_data)
    if not owner:
        return
    name = tournament_data.get('name') or 'your tournament'
    send_to_user(
        db,
        owner,
        "You're on the clock",
        name,
        {'type': 'your_turn', 'tournamentId': tournament_id},
    )


def notify_draft_complete(db, tournament_id: str, tournament_data: dict) -> None:
    name = tournament_data.get('name') or 'your tournament'
    data = {'type': 'draft_complete', 'tournamentId': tournament_id}
    owners = _team_owner_uids(tournament_data)
    send_to_users(db, owners, 'Draft complete', f'{name} — view your team', data)
