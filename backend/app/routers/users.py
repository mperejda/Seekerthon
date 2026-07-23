import asyncio
import base58
import logging
import math
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
from app.models.schemas import UserCreate, UserResponse, WalletChallenge, AuthToken, UserActivityResponse, ActivityVotedProject, ActivitySupportNft


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

    # Look up existing user so we can fall back to cached values if RPC fails.
    existing = db.table("users").select("skr_balance,skr_staked,is_seeker_verified,has_builder_pass,skr_id").eq("wallet_address", body.wallet_address).maybe_single().execute()
    cached = existing.data or {}

    # Run all on-chain checks in parallel with a 5 s timeout each.
    # Falls back to cached DB values for returning users; 0/False for brand-new ones.
    _FAILED = object()
    _TIMEOUT = 5.0

    async def _timed(coro, fallback):
        try:
            return await asyncio.wait_for(coro, timeout=_TIMEOUT)
        except Exception as exc:
            log.warning("On-chain check failed or timed out for %s: %s", body.wallet_address, exc)
            return fallback

    (
        (skr_balance, skr_staked),
        is_seeker_verified,
        has_builder_pass,
        skr_id_result,
    ) = await asyncio.gather(
        _timed(get_skr_balance(body.wallet_address), (cached.get("skr_balance", 0), cached.get("skr_staked", 0))),
        _timed(verify_seeker_genesis_holder(body.wallet_address), cached.get("is_seeker_verified", False)),
        _timed(verify_builder_pass_holder(body.wallet_address), cached.get("has_builder_pass", False)),
        _timed(get_skr_id(body.wallet_address), _FAILED),
    )

    # Only on-chain staked SKR contributes to vote weight — liquid balance does not.
    vote_multiplier = compute_vote_weight(skr_staked, has_builder_pass)

    user_data = {
        "wallet_address": body.wallet_address,
        "skr_balance": skr_balance,
        "skr_staked": skr_staked,
        "vote_multiplier": vote_multiplier,
        "is_seeker_verified": is_seeker_verified,
        "has_builder_pass": has_builder_pass,
    }
    if skr_id_result is not _FAILED:
        user_data["skr_id"] = skr_id_result

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

    votes_res = db.table("votes").select("project_id").eq("voter_id", user_id).execute()
    project_ids = [row["project_id"] for row in (votes_res.data or [])]
    votes_cast = len(project_ids)
    hackathons_voted = 0
    if project_ids:
        projects_res = db.table("projects").select("hackathon_id").in_("id", project_ids).execute()
        hackathons_voted = len({row["hackathon_id"] for row in (projects_res.data or [])})

    support_res = db.table("support_nft_mints").select("id", count="exact").eq("user_id", user_id).eq("status", "confirmed").execute()
    support_nfts_minted = support_res.count or 0

    skr_staked_rank = None
    skr_staked_percentile = None
    if skr_staked > 0:
        above_res = db.table("users").select("id", count="exact").gt("skr_staked", skr_staked).execute()
        total_res = db.table("users").select("id", count="exact").gt("skr_staked", 0).execute()
        count_above = above_res.count or 0
        total_stakers = total_res.count or 0
        skr_staked_rank = count_above + 1
        if total_stakers > 0:
            skr_staked_percentile = max(1, math.ceil(count_above / total_stakers * 100))

    return UserResponse(**result.data[0], votes_cast=votes_cast, hackathons_voted=hackathons_voted, support_nfts_minted=support_nfts_minted, skr_staked_rank=skr_staked_rank, skr_staked_percentile=skr_staked_percentile)


@router.get("/me/activity", response_model=UserActivityResponse)
async def get_my_activity(request: Request):
    db = get_supabase_admin()
    user_id = request.state.user_id

    # Voted projects
    votes_res = db.table("votes").select("project_id").eq("voter_id", user_id).execute()
    vote_project_ids = [row["project_id"] for row in (votes_res.data or [])]
    voted_projects = []
    if vote_project_ids:
        proj_res = db.table("projects").select("id, name, hackathon_id").in_("id", vote_project_ids).execute()
        hack_ids = list({p["hackathon_id"] for p in (proj_res.data or [])})
        hack_res = db.table("hackathons").select("id, title").in_("id", hack_ids).execute()
        hack_map = {h["id"]: h["title"] for h in (hack_res.data or [])}
        for p in (proj_res.data or []):
            voted_projects.append(ActivityVotedProject(
                project_id=p["id"],
                project_name=p["name"],
                hackathon_title=hack_map.get(p["hackathon_id"], ""),
            ))

    # Support NFTs minted
    support_res = db.table("support_nft_mints").select("project_id, hackathon_id, asset_id").eq("user_id", user_id).eq("status", "confirmed").execute()
    support_project_ids = list({row["project_id"] for row in (support_res.data or [])})
    support_nfts = []
    if support_project_ids:
        s_proj_res = db.table("projects").select("id, name").in_("id", support_project_ids).execute()
        s_proj_map = {p["id"]: p["name"] for p in (s_proj_res.data or [])}
        s_hack_ids = list({row["hackathon_id"] for row in (support_res.data or []) if row.get("hackathon_id")})
        s_hack_res = db.table("hackathons").select("id, title").in_("id", s_hack_ids).execute()
        s_hack_map = {h["id"]: h["title"] for h in (s_hack_res.data or [])}
        for row in (support_res.data or []):
            support_nfts.append(ActivitySupportNft(
                project_id=row["project_id"],
                project_name=s_proj_map.get(row["project_id"], ""),
                hackathon_title=s_hack_map.get(row.get("hackathon_id", ""), ""),
                asset_id=row.get("asset_id"),
            ))

    return UserActivityResponse(voted_projects=voted_projects, support_nfts=support_nfts)



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
