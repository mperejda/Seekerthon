import json
import logging
import firebase_admin
from firebase_admin import credentials, messaging
from app.config import get_settings
from app.db import get_supabase_admin

_log = logging.getLogger(__name__)
_firebase_app = None


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


async def send_to_hackathon_registrants(hackathon_id: str, title: str, body: str) -> None:
    if _get_app() is None:
        _log.warning("notification: Firebase not configured — skipping hackathon=%s", hackathon_id)
        return

    db = get_supabase_admin()

    regs = db.table("hackathon_registrations").select("user_id").eq("hackathon_id", hackathon_id).execute()
    if not regs.data:
        return

    user_ids = [r["user_id"] for r in regs.data]

    tokens_res = db.table("device_tokens").select("token").in_("user_id", user_ids).execute()
    if not tokens_res.data:
        _log.info("notification: no device tokens hackathon=%s", hackathon_id)
        return

    tokens = [t["token"] for t in tokens_res.data]

    message = messaging.MulticastMessage(
        notification=messaging.Notification(title=title, body=body),
        tokens=tokens,
        android=messaging.AndroidConfig(priority="high"),
    )
    try:
        response = messaging.send_each_for_multicast(message)
        _log.info(
            "notification: sent hackathon=%s success=%d failure=%d",
            hackathon_id, response.success_count, response.failure_count,
        )
    except Exception as exc:
        _log.error("notification: FCM send failed hackathon=%s err=%s", hackathon_id, exc)
