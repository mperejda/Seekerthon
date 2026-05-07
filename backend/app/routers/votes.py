from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Request, Query
from typing import List

from app.db import get_supabase_admin
from app.models.schemas import VotePrepareRequest, VotePrepareResponse, VoteConfirmRequest, VoteResponse
from app.services.solana_service import (
    get_skr_balance,
    compute_vote_weight,
    build_vote_transaction,
    verify_transaction_on_chain,
    verify_seeker_genesis_holder,
)

router = APIRouter()

_VOTE_TTL_MINUTES = 2


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


@router.post("/prepare", response_model=VotePrepareResponse)
async def prepare_vote(body: VotePrepareRequest, request: Request):
    """
    Step 1: Build an unsigned Solana vote transaction.
    Android app sends this to Seeker SDK for signing.
    Vote weight is locked in pending_votes at this point.
    """
    db = get_supabase_admin()
    user_id = request.state.user_id
    wallet = request.state.wallet_address

    # Fast path: use the flag cached at login time.
    # Fall back to a live mainnet check if the DB says False — handles the case
    # where the collection address was fixed after the user last logged in.
    user_row = db.table("users").select("is_seeker_verified").eq("id", user_id).maybe_single().execute()
    is_verified = (user_row.data or {}).get("is_seeker_verified", False)
    if not is_verified:
        try:
            is_verified = await verify_seeker_genesis_holder(wallet)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("Genesis check error for %s: %s", wallet, exc)
            raise HTTPException(status_code=503, detail="Could not verify NFT ownership — try again")
        if is_verified:
            db.table("users").update({"is_seeker_verified": True}).eq("id", user_id).execute()
    if not is_verified:
        raise HTTPException(status_code=403, detail="Must hold a Seeker Genesis NFT to vote")

    # DB-level duplicate guard (Solana PDA is the on-chain guard)
    existing = db.table("votes").select("id") \
        .eq("voter_id", user_id) \
        .eq("project_id", str(body.project_id)) \
        .execute()
    if existing.data:
        raise HTTPException(status_code=409, detail="Already voted for this project")

    project = db.table("projects").select("*, hackathons(onchain_pda)") \
        .eq("id", str(body.project_id)).single().execute()
    if not project.data:
        raise HTTPException(status_code=404, detail="Project not found")

    project_pda = project.data.get("onchain_pda") or None  # None → memo tx on mainnet
    hackathon_pda = (project.data.get("hackathons") or {}).get("onchain_pda") or None

    # Compute and lock vote weight now — not at confirm time
    _, skr_staked = await get_skr_balance(wallet)
    vote_weight = compute_vote_weight(skr_staked)
    vote_weight_bps = int(vote_weight * 10000)

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=_VOTE_TTL_MINUTES)

    # Upsert into pending_votes to lock the weight for this (voter, project) pair
    db.table("pending_votes").upsert({
        "voter_id": user_id,
        "project_id": str(body.project_id),
        "weight": vote_weight,
        "expires_at": expires_at.isoformat(),
    }).execute()

    tx_b64 = await build_vote_transaction(wallet, project_pda, hackathon_pda, vote_weight_bps)

    return VotePrepareResponse(
        transaction_b64=tx_b64,
        vote_weight=vote_weight,
        voter_skr_staked=skr_staked,
        expires_at=expires_at,
    )


@router.post("/confirm", response_model=VoteResponse)
async def confirm_vote(body: VoteConfirmRequest, request: Request):
    """
    Step 2: Android app has signed and broadcast the tx.
    We verify it landed on-chain using the weight locked at prepare time, then write to DB.
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

    project = db.table("projects").select("onchain_pda").eq("id", str(body.project_id)).single().execute()
    if not project.data:
        raise HTTPException(status_code=404, detail="Project not found")

    project_pda = project.data.get("onchain_pda") or None
    verified = await verify_transaction_on_chain(body.tx_signature, project_pda, wallet)
    if not verified:
        raise HTTPException(status_code=400, detail="Transaction not confirmed on-chain")

    # Insert vote using the weight locked at prepare time
    vote_data = {
        "voter_id": user_id,
        "project_id": str(body.project_id),
        "weight": vote_weight,
        "tx_signature": body.tx_signature,
    }
    result = db.table("votes").insert(vote_data).execute()

    # Clean up pending vote and update project tally atomically via RPC
    db.table("pending_votes").delete() \
        .eq("voter_id", user_id).eq("project_id", str(body.project_id)).execute()
    db.rpc("increment_vote_count", {
        "p_project_id": str(body.project_id),
        "p_weight": vote_weight,
    }).execute()

    return VoteResponse(**result.data[0])


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
