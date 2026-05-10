import base58
import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Request, Query
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError
from typing import List

from app.db import get_supabase_admin
from app.models.schemas import VotePrepareRequest, VotePrepareResponse, VoteConfirmRequest, VoteResponse
from app.services.solana_service import (
    get_skr_balance,
    compute_vote_weight,
    verify_seeker_genesis_holder,
)

log = logging.getLogger(__name__)
router = APIRouter()

_VOTE_TTL_MINUTES = 5


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _build_vote_message(project_id: str, wallet: str, weight_bps: int, expires_unix: int) -> str:
    return f"seeker-vote:v1:{project_id}:{wallet}:{weight_bps}:{expires_unix}"


@router.post("/prepare", response_model=VotePrepareResponse)
async def prepare_vote(body: VotePrepareRequest, request: Request):
    """
    Step 1: Return a structured vote message for the wallet to sign with ed25519.
    Vote weight is locked in pending_votes at this point.
    No Solana transaction is built — no tx fees, no simulation.
    """
    db = get_supabase_admin()
    user_id = request.state.user_id
    wallet = request.state.wallet_address

    # Fast path: use the flags cached at login time.
    # Fall back to a live mainnet check if the DB says False for Genesis.
    user_row = db.table("users").select("is_seeker_verified,has_builder_pass").eq("id", user_id).maybe_single().execute()
    is_verified = (user_row.data or {}).get("is_seeker_verified", False)
    has_builder_pass = (user_row.data or {}).get("has_builder_pass", False)
    if not is_verified:
        try:
            is_verified = await verify_seeker_genesis_holder(wallet)
        except Exception as exc:
            log.error("Genesis check error for %s: %s", wallet, exc)
            raise HTTPException(status_code=503, detail="Could not verify NFT ownership — try again")
        if is_verified:
            db.table("users").update({"is_seeker_verified": True}).eq("id", user_id).execute()
    if not is_verified:
        raise HTTPException(status_code=403, detail="Must hold a Seeker Genesis NFT to vote")

    # DB-level duplicate guard
    existing = db.table("votes").select("id") \
        .eq("voter_id", user_id) \
        .eq("project_id", str(body.project_id)) \
        .execute()
    if existing.data:
        raise HTTPException(status_code=409, detail="Already voted for this project")

    project = db.table("projects").select("id").eq("id", str(body.project_id)).maybe_single().execute()
    if not project.data:
        raise HTTPException(status_code=404, detail="Project not found")

    # Compute and lock vote weight now — not at confirm time
    skr_balance, skr_staked = await get_skr_balance(wallet)
    effective_skr = skr_balance + skr_staked
    vote_weight = compute_vote_weight(effective_skr, has_builder_pass)
    vote_weight_bps = int(vote_weight * 10000)

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=_VOTE_TTL_MINUTES)
    expires_unix = int(expires_at.timestamp())

    vote_message = _build_vote_message(str(body.project_id), wallet, vote_weight_bps, expires_unix)
    log.info("Vote prepare: voter=%s project=%s weight_bps=%d msg=%s", user_id, body.project_id, vote_weight_bps, vote_message)

    db.table("pending_votes").upsert({
        "voter_id": user_id,
        "project_id": str(body.project_id),
        "weight": vote_weight,
        "expires_at": expires_at.isoformat(),
    }).execute()

    return VotePrepareResponse(
        vote_message=vote_message,
        vote_weight=vote_weight,
        voter_skr_staked=effective_skr,
        expires_at=expires_at,
    )


@router.post("/confirm", response_model=VoteResponse)
async def confirm_vote(body: VoteConfirmRequest, request: Request):
    """
    Step 2: Wallet signed the vote_message with ed25519.
    We verify the signature, then write the vote to DB.
    """
    db = get_supabase_admin()
    user_id = request.state.user_id
    wallet = request.state.wallet_address

    # Retrieve locked weight from prepare step
    pending = db.table("pending_votes").select("*") \
        .eq("voter_id", user_id) \
        .eq("project_id", str(body.project_id)) \
        .maybe_single().execute()
    if not pending.data:
        raise HTTPException(status_code=400, detail="No pending vote found — call /prepare first")
    if datetime.now(timezone.utc) > _parse_dt(pending.data["expires_at"]):
        db.table("pending_votes").delete() \
            .eq("voter_id", user_id).eq("project_id", str(body.project_id)).execute()
        raise HTTPException(status_code=400, detail="Vote preparation expired — call /prepare again")

    vote_weight = pending.data["weight"]
    weight_bps = int(vote_weight * 10000)
    expires_unix = int(_parse_dt(pending.data["expires_at"]).timestamp())

    # Reconstruct and verify the message matches what was sent
    expected_message = _build_vote_message(str(body.project_id), wallet, weight_bps, expires_unix)
    if body.vote_message != expected_message:
        log.warning("Vote message mismatch: expected=%s got=%s", expected_message, body.vote_message)
        raise HTTPException(status_code=400, detail="Vote message does not match pending vote")

    # Verify ed25519 signature (same pattern as login)
    try:
        pubkey_bytes = base58.b58decode(wallet)
        sig_bytes = base58.b58decode(body.tx_signature)
        vk = VerifyKey(pubkey_bytes)
        vk.verify(body.vote_message.encode(), sig_bytes)
        log.info("Vote signature verified: voter=%s project=%s", user_id, body.project_id)
    except BadSignatureError:
        raise HTTPException(status_code=401, detail="Invalid vote signature")
    except Exception as exc:
        log.error("Signature verification error: %s", exc)
        raise HTTPException(status_code=400, detail="Malformed wallet address or signature")

    # Insert vote
    vote_data = {
        "voter_id": user_id,
        "project_id": str(body.project_id),
        "weight": vote_weight,
        "tx_signature": body.tx_signature,
    }
    result = db.table("votes").insert(vote_data).execute()

    # Clean up pending vote and update project tally
    db.table("pending_votes").delete() \
        .eq("voter_id", user_id).eq("project_id", str(body.project_id)).execute()
    db.rpc("increment_vote_count", {
        "p_project_id": str(body.project_id),
        "p_weight": vote_weight,
    }).execute()

    return VoteResponse(**result.data[0])


@router.get("/mine", response_model=List[str])
async def get_my_votes(request: Request):
    """Return project IDs the current user has already voted on."""
    db = get_supabase_admin()
    user_id = request.state.user_id
    result = db.table("votes").select("project_id").eq("voter_id", user_id).execute()
    return [row["project_id"] for row in result.data]


@router.get("/project/{project_id}", response_model=List[VoteResponse])
async def get_project_votes(
    project_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    db = get_supabase_admin()
    result = db.table("votes").select("*") \
        .eq("project_id", project_id) \
        .range(offset, offset + limit - 1) \
        .execute()
    return [VoteResponse(**v) for v in result.data]
