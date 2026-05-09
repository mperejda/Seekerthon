import base58
import logging
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Request
from jose import jwt

log = logging.getLogger(__name__)
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

from app.config import get_settings
from app.db import get_supabase_admin
from app.models.schemas import UserCreate, UserResponse, WalletChallenge, AuthToken
from app.services.solana_service import (
    get_skr_balance,
    compute_vote_weight,
    verify_seeker_genesis_holder,
)

router = APIRouter()
_settings = get_settings()


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


@router.get("/challenge", response_model=WalletChallenge)
async def get_challenge(wallet_address: str):
    """Issue a sign challenge for wallet-based login."""
    challenge = f"seeker-hackathon-login:{wallet_address}:{secrets.token_hex(16)}"
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    db = get_supabase_admin()
    db.table("challenges").insert({
        "challenge": challenge,
        "expires_at": expires_at.isoformat(),
    }).execute()
    return WalletChallenge(challenge=challenge, expires_at=expires_at)


@router.post("/login", response_model=AuthToken)
async def login(body: UserCreate):
    """
    Verify wallet signature and issue JWT.
    The Android app signs the challenge with Seeker SDK and sends signature here.
    """
    db = get_supabase_admin()

    # Validate challenge from DB
    row = db.table("challenges").select("*").eq("challenge", body.challenge).maybe_single().execute()
    if not row.data:
        raise HTTPException(status_code=400, detail="Challenge expired or invalid")
    if datetime.now(timezone.utc) > _parse_dt(row.data["expires_at"]):
        db.table("challenges").delete().eq("challenge", body.challenge).execute()
        raise HTTPException(status_code=400, detail="Challenge expired or invalid")
    db.table("challenges").delete().eq("challenge", body.challenge).execute()

    # Verify ed25519 signature
    try:
        pubkey_bytes = base58.b58decode(body.wallet_address)
        sig_bytes = base58.b58decode(body.signature)
        vk = VerifyKey(pubkey_bytes)
        vk.verify(body.challenge.encode(), sig_bytes)
    except BadSignatureError:
        raise HTTPException(status_code=401, detail="Invalid signature")
    except Exception:
        raise HTTPException(status_code=400, detail="Malformed wallet address or signature")

    # Fetch on-chain state — fall back to safe defaults if RPC is rate-limited
    try:
        skr_balance, skr_staked = await get_skr_balance(body.wallet_address)
    except Exception as exc:
        log.warning("SKR balance lookup failed for %s: %s", body.wallet_address, exc)
        skr_balance, skr_staked = 0, 0
    vote_multiplier = compute_vote_weight(skr_balance + skr_staked)
    try:
        is_seeker_verified = await verify_seeker_genesis_holder(body.wallet_address)
    except Exception as exc:
        log.warning("Genesis check failed for %s: %s", body.wallet_address, exc)
        is_seeker_verified = False

    user_data = {
        "wallet_address": body.wallet_address,
        "skr_balance": skr_balance,
        "skr_staked": skr_staked,
        "vote_multiplier": vote_multiplier,
        "is_seeker_verified": is_seeker_verified,
    }

    result = db.table("users").upsert(user_data, on_conflict="wallet_address").execute()
    user = result.data[0]

    payload = {
        "sub": str(user["id"]),
        "wallet": body.wallet_address,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=_settings.jwt_expire_minutes),
    }
    token = jwt.encode(payload, _settings.jwt_secret, algorithm=_settings.jwt_algorithm)
    return AuthToken(access_token=token, user=UserResponse(**user))


@router.get("/me", response_model=UserResponse)
async def get_me(request: Request):
    """Get current user profile with refreshed on-chain SKR state."""
    db = get_supabase_admin()
    user_id = request.state.user_id
    wallet = request.state.wallet_address

    existing = db.table("users").select("*").eq("id", user_id).maybe_single().execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="User not found")

    skr_balance, skr_staked = await get_skr_balance(wallet)
    vote_multiplier = compute_vote_weight(skr_balance + skr_staked)
    try:
        is_seeker_verified = await verify_seeker_genesis_holder(wallet)
    except Exception as exc:
        log.warning("Genesis check failed for %s, using cached value: %s", wallet, exc)
        is_seeker_verified = existing.data.get("is_seeker_verified", False)

    result = db.table("users").update({
        "skr_balance": skr_balance,
        "skr_staked": skr_staked,
        "vote_multiplier": vote_multiplier,
        "is_seeker_verified": is_seeker_verified,
    }).eq("id", user_id).execute()

    return UserResponse(**result.data[0])



@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: str):
    db = get_supabase_admin()
    result = db.table("users").select("*").eq("id", user_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(**result.data)
