from datetime import datetime, timedelta, timezone
import logging
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from jose import jwt
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter()
log = logging.getLogger(__name__)

CHERRY_APP_ID = "735413f4-d9a3-4b90-af2f-845ba3ea97cd"


class CherryEmbedTokenResponse(BaseModel):
    token: str


@router.post("/cherry-embed-token", response_model=CherryEmbedTokenResponse)
async def create_cherry_embed_token(request: Request, response: Response):
    wallet_address = getattr(request.state, "wallet_address", None)
    if not wallet_address:
        raise HTTPException(status_code=401, detail="Missing authenticated wallet")
    app_secret = get_settings().cherry_app_secret.strip()
    if not app_secret:
        raise HTTPException(status_code=503, detail="Cherry chat is not configured")

    now = datetime.now(timezone.utc)
    issued_at = now - timedelta(seconds=60)
    expires_at = issued_at + timedelta(minutes=5)
    jti = str(uuid4())
    token = jwt.encode(
        {
            "sub": wallet_address,
            "app_id": CHERRY_APP_ID,
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
            "jti": jti,
        },
        app_secret,
        algorithm="HS256",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    log.info("Minted Cherry embed token app_id=%s", CHERRY_APP_ID)
    return CherryEmbedTokenResponse(token=token)
