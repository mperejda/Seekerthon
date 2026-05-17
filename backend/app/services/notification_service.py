import json
import logging
from dataclasses import dataclass

import firebase_admin
from firebase_admin import credentials, messaging
from app.config import get_settings
from app.db import get_supabase_admin

_log = logging.getLogger(__name__)
_firebase_app = None


@dataclass(frozen=True)
class NotificationDispatchResult:
    delivered: bool
    recipient_count: int = 0
    token_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    reason: str | None = None


def _get_app():
    global _firebase_app
    if _firebase_app is not None:
        return _firebase_app
    s = get_settings()
    if not s.firebase_service_account_json:
        return None
    try:
        cred = credentials.Certificate(json.loads(s.firebase_service_account_json))
        _firebase_app = firebase_admin.initialize_app(cred)
    except Exception as exc:
        _log.error("notification: Firebase init failed err=%s", exc)
    return _firebase_app


async def send_to_hackathon_registrants(hackathon_id: str, title: str, body: str) -> NotificationDispatchResult:
    if _get_app() is None:
        _log.warning("notification: Firebase not configured — skipping hackathon=%s", hackathon_id)
        return NotificationDispatchResult(delivered=False, reason="firebase_not_configured")

    db = get_supabase_admin()

    tokens_res = db.table("device_tokens").select("token").execute()
    if not tokens_res.data:
        _log.info("notification: no device tokens hackathon=%s", hackathon_id)
        return NotificationDispatchResult(
            delivered=False,
            reason="no_device_tokens",
        )

    tokens = [t["token"] for t in tokens_res.data]

    message = messaging.MulticastMessage(
        notification=messaging.Notification(title=title, body=body),
        tokens=tokens,
        android=messaging.AndroidConfig(priority="high"),
    )
    try:
        response = messaging.send_each_for_multicast(message)
        delivered = response.success_count > 0
        _log.info(
            "notification: sent hackathon=%s success=%d failure=%d",
            hackathon_id, response.success_count, response.failure_count,
        )
        return NotificationDispatchResult(
            delivered=delivered,
            token_count=len(tokens),
            success_count=response.success_count,
            failure_count=response.failure_count,
            reason=None if delivered else "no_successful_deliveries",
        )
    except Exception as exc:
        _log.error("notification: FCM send failed hackathon=%s err=%s", hackathon_id, exc)
        return NotificationDispatchResult(
            delivered=False,
            token_count=len(tokens),
            reason="fcm_error",
        )
