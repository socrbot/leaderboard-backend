"""FCM push notifications for draft workflow.

Tokens are stored at users/{uid}/fcmTokens/{token} with doc body:
  { platform: 'android'|'ios'|'web', createdAt }

Stale tokens (NotRegistered / Unregistered / invalid-argument) are deleted
automatically when a send fails.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable, Optional

from firebase_admin import messaging
from google.api_core.exceptions import AlreadyExists

logger = logging.getLogger(__name__)
ON_CLOCK_THROTTLE_SECONDS = 8


def _read_user_tokens(db, uid: str) -> list[str]:
    if not uid:
        return []
    try:
        snaps = db.collection('users').document(uid).collection('fcmTokens').stream()
        return [s.id for s in snaps]
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("Failed to read fcmTokens for %s: %s", uid, e)
        return []


def _mark_on_clock_event_if_new(db, tournament_id: str, pick_number: int, owner_uid: str) -> bool:
    """Return True only for first-seen on-clock event for this tournament+pick."""
    if not tournament_id or not pick_number:
        return False
    try:
        event_ref = (
            db.collection('tournaments')
            .document(tournament_id)
            .collection('notificationEvents')
            .document(f'on_clock_{pick_number}')
        )
        event_ref.create({
            'type': 'on_clock',
            'pickNumber': int(pick_number),
            'ownerUid': owner_uid,
            'createdAt': datetime.now(timezone.utc),
        })
        return True
    except AlreadyExists:
        return False
    except Exception as e:  # pragma: no cover
        logger.warning("Could not persist on-clock dedupe key for %s/%s: %s", tournament_id, pick_number, e)
        # Fail open to avoid blocking a valid notification when dedupe bookkeeping fails.
        return True


def _is_on_clock_throttled(db, uid: str, tournament_id: str, pick_number: int) -> bool:
    """Guardrail: suppress rapid duplicate sends for the same user's same pick context."""
    if not uid or not tournament_id or not pick_number:
        return False
    try:
        state_ref = db.collection('users').document(uid).collection('notificationState').document('draft_on_clock')
        snap = state_ref.get()
        now = datetime.now(timezone.utc)
        if snap.exists:
            payload = snap.to_dict() or {}
            last_tournament = payload.get('tournamentId')
            last_pick = payload.get('pickNumber')
            last_sent_at = payload.get('lastSentAt')
            if last_tournament == tournament_id and int(last_pick or 0) == int(pick_number) and last_sent_at:
                sent_at = last_sent_at if getattr(last_sent_at, 'tzinfo', None) else last_sent_at.replace(tzinfo=timezone.utc)
                if (now - sent_at).total_seconds() < ON_CLOCK_THROTTLE_SECONDS:
                    return True
        state_ref.set({
            'tournamentId': tournament_id,
            'pickNumber': int(pick_number),
            'lastSentAt': now,
        }, merge=True)
        return False
    except Exception as e:  # pragma: no cover
        logger.warning("Could not evaluate on-clock throttle for uid=%s: %s", uid, e)
        return False


def _is_draft_notifications_enabled(db, uid: str) -> bool:
    if not uid:
        return False
    try:
        user_doc = db.collection('users').document(uid).get()
        if not user_doc.exists:
            return True
        prefs = (user_doc.to_dict() or {}).get('notificationPreferences') or {}
        return bool(prefs.get('draftOnClock', True))
    except Exception as e:  # pragma: no cover
        logger.warning("Failed to read notification preferences for %s: %s", uid, e)
        return True


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
    if not _is_draft_notifications_enabled(db, uid):
        return 0

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


def _compute_current_pick_context(tournament_data: dict) -> tuple[Optional[str], Optional[int]]:
    """Return (ownerUid, nextPickNumber) for who's up next, or (None, None)."""
    teams = tournament_data.get('teams') or []
    draft_picks = tournament_data.get('draftPicks') or []
    num_teams = len(teams)
    if num_teams == 0:
        return None, None
    total_picks = 4 * num_teams
    if len(draft_picks) >= total_picks:
        return None, None
    next_pick_number = len(draft_picks) + 1
    round_idx = (next_pick_number - 1) // num_teams
    pick_in_round = (next_pick_number - 1) % num_teams
    sorted_teams = sorted(teams, key=lambda t: t.get('draftOrder', 999))
    if round_idx % 2 == 0:
        current = sorted_teams[pick_in_round]
    else:
        current = sorted_teams[num_teams - 1 - pick_in_round]
    return current.get('ownerUid'), next_pick_number


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
    owner, next_pick_number = _compute_current_pick_context(tournament_data)
    if not owner:
        return
    if not _mark_on_clock_event_if_new(db, tournament_id, int(next_pick_number or 0), owner):
        logger.info("Skipped duplicate on-clock notification for tournament=%s pick=%s", tournament_id, next_pick_number)
        return
    if _is_on_clock_throttled(db, owner, tournament_id, int(next_pick_number or 0)):
        logger.info("Skipped throttled on-clock notification for tournament=%s pick=%s uid=%s", tournament_id, next_pick_number, owner)
        return
    name = tournament_data.get('name') or 'your tournament'
    send_to_user(
        db,
        owner,
        "You're on the clock",
        name,
        {
            'type': 'your_turn',
            'tournamentId': tournament_id,
            'nextPickNumber': int(next_pick_number or 0),
        },
    )


def notify_draft_complete(db, tournament_id: str, tournament_data: dict) -> None:
    name = tournament_data.get('name') or 'your tournament'
    data = {'type': 'draft_complete', 'tournamentId': tournament_id}
    owners = _team_owner_uids(tournament_data)
    send_to_users(db, owners, 'Draft complete', f'{name} — view your team', data)
