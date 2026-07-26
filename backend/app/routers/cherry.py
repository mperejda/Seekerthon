from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from jose import jwt
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter()
_settings = get_settings()

CHERRY_APP_ID = "735413f4-d9a3-4b90-af2f-845ba3ea97cd"


class CherryEmbedTokenResponse(BaseModel):
    token: str
    wallet_address: str


@router.post("/cherry-embed-token", response_model=CherryEmbedTokenResponse)
async def create_cherry_embed_token(request: Request):
    wallet_address = getattr(request.state, "wallet_address", None)
    if not wallet_address:
        raise HTTPException(status_code=401, detail="Missing authenticated wallet")
    if not _settings.cherry_app_secret:
        raise HTTPException(status_code=503, detail="Cherry chat is not configured")

    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": wallet_address,
            "app_id": CHERRY_APP_ID,
            "exp": now + timedelta(minutes=5),
            "jti": str(uuid4()),
        },
        _settings.cherry_app_secret,
        algorithm="HS256",
    )
    return CherryEmbedTokenResponse(token=token, wallet_address=wallet_address)
