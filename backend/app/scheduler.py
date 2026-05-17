import logging
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.db import get_supabase_admin
from app.services import notification_service

_log = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


async def _check_hackathon_notifications() -> None:
    try:
        db = get_supabase_admin()
        now = datetime.now(timezone.utc)

        result = db.table("hackathons") \
            .select("id,title,status,voting_start,voting_end,notifications_sent") \
            .neq("status", "draft") \
            .execute()

        for h in result.data or []:
            hid = h["id"]
            title = h["title"]
            status = h["status"]
            if not h.get("voting_start") or not h.get("voting_end"):
                continue
            voting_start = _parse_dt(h["voting_start"])
            voting_end = _parse_dt(h["voting_end"])
            sent = dict(h.get("notifications_sent") or {})

            if status == "open" and now >= voting_start and now < voting_end:
                db.table("hackathons").update({"status": "voting"}).eq("id", hid).execute()
                status = "voting"

            # 1. Voting opened
            if status == "voting" and not sent.get("voting_opened"):
                dispatch = await notification_service.send_to_hackathon_registrants(
                    hid,
                    "Voting is open!",
                    f"Cast your vote for {title} now.",
                )
                if dispatch.delivered:
                    sent["voting_opened"] = True
                    db.table("hackathons").update({"notifications_sent": sent}).eq("id", hid).execute()

            # 2. 5 hours left
            if status == "voting" and not sent.get("five_hour_warning"):
                time_left = voting_end - now
                if timedelta(0) < time_left <= timedelta(hours=5):
                    dispatch = await notification_service.send_to_hackathon_registrants(
                        hid,
                        "5 hours left to vote!",
                        f"Don't miss your chance to vote in {title}.",
                    )
                    if dispatch.delivered:
                        sent["five_hour_warning"] = True
                        db.table("hackathons").update({"notifications_sent": sent}).eq("id", hid).execute()

            # 3. Winner announced
            if status == "completed" and not sent.get("winner_announced"):
                winner = db.table("projects") \
                    .select("name") \
                    .eq("hackathon_id", hid) \
                    .eq("status", "winner") \
                    .maybe_single() \
                    .execute()
                if winner and winner.data:
                    dispatch = await notification_service.send_to_hackathon_registrants(
                        hid,
                        "Winner announced!",
                        f"The winner of {title} has been revealed.",
                    )
                    if dispatch.delivered:
                        sent["winner_announced"] = True
                        db.table("hackathons").update({"notifications_sent": sent}).eq("id", hid).execute()

    except Exception as exc:
        _log.error("scheduler: notification check failed err=%s", exc, exc_info=True)


def start() -> None:
    scheduler.add_job(
        _check_hackathon_notifications,
        "interval",
        seconds=60,
        max_instances=1,
        id="hackathon_notifications",
    )
    scheduler.start()
    _log.info("scheduler: started")


def shutdown() -> None:
    scheduler.shutdown(wait=False)
    _log.info("scheduler: stopped")
