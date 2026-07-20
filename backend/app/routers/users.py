import base58
import logging
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Request, Response
from jose import jwt
from pydantic import BaseModel

log = logging.getLogger(__name__)
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

from app.config import get_settings
from app.db import get_supabase_admin
from app.middleware.auth import SESSION_COOKIE_NAME
from app.models.schemas import UserCreate, UserResponse, WalletChallenge, AuthToken


class DeviceTokenRequest(BaseModel):
    token: str
from app.services.solana_service import (
    get_skr_balance,
    get_skr_id,
    compute_vote_weight,
    verify_builder_pass_holder,
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
        "wallet_address": wallet_address,
        "expires_at": expires_at.isoformat(),
    }).execute()
    return WalletChallenge(challenge=challenge, expires_at=expires_at)


def _set_session_cookie(response: Response, token: str) -> None:
    """Mirror the JWT into an httpOnly cookie so the webapp does not need to
    keep it in localStorage where any XSS could exfiltrate it. The mobile app
    ignores this and reads access_token from the response body instead."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=_settings.jwt_expire_minutes * 60,
        path="/",
    )


@router.post("/login", response_model=AuthToken)
async def login(body: UserCreate, response: Response):
    """
    Verify wallet signature and issue JWT.
    The Android app signs the challenge with Seeker SDK and sends signature here.
    """
    db = get_supabase_admin()

    # Validate challenge from DB — must exist, be unexpired, and bound to the
    # same wallet that requested it. The wallet binding closes a window where
    # a challenge issued for wallet A could be consumed by wallet B.
    row = db.table("challenges").select("*").eq("challenge", body.challenge).maybe_single().execute()
    if not row.data:
        raise HTTPException(status_code=400, detail="Challenge expired or invalid")
    if datetime.now(timezone.utc) > _parse_dt(row.data["expires_at"]):
        db.table("challenges").delete().eq("challenge", body.challenge).execute()
        raise HTTPException(status_code=400, detail="Challenge expired or invalid")
    bound_wallet = row.data.get("wallet_address")
    if bound_wallet and bound_wallet != body.wallet_address:
        db.table("challenges").delete().eq("challenge", body.challenge).execute()
        raise HTTPException(status_code=400, detail="Challenge does not belong to this wallet")
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
    try:
        is_seeker_verified = await verify_seeker_genesis_holder(body.wallet_address)
    except Exception as exc:
        log.warning("Genesis check failed for %s: %s", body.wallet_address, exc)
        is_seeker_verified = False
    try:
        has_builder_pass = await verify_builder_pass_holder(body.wallet_address)
    except Exception as exc:
        log.warning("Builder pass check failed for %s: %s", body.wallet_address, exc)
        has_builder_pass = False
    # Only on-chain staked SKR contributes to vote weight — liquid balance does not.
    vote_multiplier = compute_vote_weight(skr_staked, has_builder_pass)

    skr_id_lookup_ok = True
    skr_id = None
    try:
        skr_id = await get_skr_id(body.wallet_address)
    except Exception as exc:
        log.warning("SKR ID lookup failed for %s: %s", body.wallet_address, exc)
        skr_id_lookup_ok = False

    user_data = {
        "wallet_address": body.wallet_address,
        "skr_balance": skr_balance,
        "skr_staked": skr_staked,
        "vote_multiplier": vote_multiplier,
        "is_seeker_verified": is_seeker_verified,
        "has_builder_pass": has_builder_pass,
    }
    if skr_id_lookup_ok:
        user_data["skr_id"] = skr_id

    result = db.table("users").upsert(user_data, on_conflict="wallet_address").execute()
    user = result.data[0]

    payload = {
        "sub": str(user["id"]),
        "wallet": body.wallet_address,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=_settings.jwt_expire_minutes),
    }
    token = jwt.encode(payload, _settings.jwt_secret, algorithm=_settings.jwt_algorithm)
    _set_session_cookie(response, token)
    return AuthToken(access_token=token, user=UserResponse(**user))


@router.post("/logout", status_code=204)
async def logout(response: Response):
    """Clear the session cookie. The mobile client can just discard its
    stored access_token; this endpoint is webapp-only but exempt from auth
    so an already-expired cookie can still clean itself up."""
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


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
    try:
        is_seeker_verified = await verify_seeker_genesis_holder(wallet)
    except Exception as exc:
        log.warning("Genesis check failed for %s, using cached value: %s", wallet, exc)
        is_seeker_verified = existing.data.get("is_seeker_verified", False)
    try:
        has_builder_pass = await verify_builder_pass_holder(wallet)
    except Exception as exc:
        log.warning("Builder pass check failed for %s, using cached value: %s", wallet, exc)
        has_builder_pass = existing.data.get("has_builder_pass", False)
    vote_multiplier = compute_vote_weight(skr_staked, has_builder_pass)

    update_data: dict = {
        "skr_balance": skr_balance,
        "skr_staked": skr_staked,
        "vote_multiplier": vote_multiplier,
        "is_seeker_verified": is_seeker_verified,
        "has_builder_pass": has_builder_pass,
    }
    try:
        skr_id = await get_skr_id(wallet)
        update_data["skr_id"] = skr_id
    except Exception as exc:
        log.warning("SKR ID lookup failed for %s: %s", wallet, exc)

    result = db.table("users").update(update_data).eq("id", user_id).execute()

    return UserResponse(**result.data[0])



@router.post("/device-token", status_code=204)
async def register_device_token(body: DeviceTokenRequest, request: Request):
    """Register or refresh an FCM device token for the authenticated user.

    A given FCM token only ever belongs to one user — re-registering the same
    token under a new user_id replaces the previous owner so the prior user
    stops receiving pushes targeted at that device.
    """
    db = get_supabase_admin()
    db.table("device_tokens").upsert(
        {"user_id": request.state.user_id, "token": body.token},
        on_conflict="token",
    ).execute()


@router.delete("/device-token", status_code=204)
async def delete_device_token(body: DeviceTokenRequest, request: Request):
    """Remove an FCM device token (on logout or token rotation)."""
    db = get_supabase_admin()
    db.table("device_tokens").delete() \
        .eq("user_id", request.state.user_id) \
        .eq("token", body.token) \
        .execute()


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: str, request: Request):
    if user_id != request.state.user_id:
        raise HTTPException(status_code=403, detail="Can only fetch your own user record")
    db = get_supabase_admin()
    result = db.table("users").select("*").eq("id", user_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(**result.data)
