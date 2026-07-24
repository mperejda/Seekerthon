import re
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.db import get_supabase_admin

log = logging.getLogger(__name__)

router = APIRouter()

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


class SignupRequest(BaseModel):
    email: str


@router.post("/newsletter/signup", status_code=201)
async def newsletter_signup(body: SignupRequest):
    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Invalid email address")
    db = get_supabase_admin()
    try:
        db.table("newsletter_signups").insert({"email": email}).execute()
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            return {"success": True}
        log.warning("Newsletter signup failed for %s: %s", email, exc)
        raise HTTPException(status_code=500, detail="Failed to save signup")
    return {"success": True}
