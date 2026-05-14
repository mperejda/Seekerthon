from datetime import datetime
from fastapi import APIRouter, HTTPException, Request, Query
from typing import List, Optional
from app.constants import PROJECT_SUBMISSION_LIMIT
from app.db import get_supabase_admin
from app.models.schemas import (
    HackathonCreate, HackathonUpdate, HackathonResponse, EscrowSetRequest,
    HackathonStatus, LeaderboardEntry, ProjectResponse,
    ClaimTxResponse, ReleaseTxResponse, VerifyReleaseRequest,
)
from app.services.solana_service import (
    build_create_escrow_transaction,
    build_claim_prize_transaction,
    build_refund_transaction,
    verify_program_transaction_on_chain,
)

router = APIRouter()


ACTIVE_HACKATHON_STATUSES = ("draft", "open", "voting", "verifying")
ACTIVE_HACKATHON_ERROR = "A hackathon is already active. Complete it before creating a new one."


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _voting_has_ended(hackathon: dict) -> bool:
    voting_end = _parse_dt(hackathon["voting_end"])
    now = datetime.now(voting_end.tzinfo) if voting_end.tzinfo else datetime.now()
    return now >= voting_end


def _project_count(db, hackathon_id: str) -> int:
    result = db.table("projects").select("id", count="exact") \
        .eq("hackathon_id", hackathon_id) \
        .not_.is_("onchain_pda", "null") \
        .execute()
    return result.count or 0


def _assert_no_other_active_hackathon(db, exclude_id: str | None = None) -> None:
    q = db.table("hackathons").select("id", count="exact").in_("status", ACTIVE_HACKATHON_STATUSES)
    if exclude_id:
        q = q.neq("id", exclude_id)
    result = q.limit(1).execute()
    if result.count or result.data:
        raise HTTPException(status_code=409, detail=ACTIVE_HACKATHON_ERROR)


@router.post("/", response_model=HackathonResponse)
async def create_hackathon(body: HackathonCreate, request: Request):
    """Organizer creates a hackathon. Escrow PDA set after on-chain tx."""
    db = get_supabase_admin()
    _assert_no_other_active_hackathon(db)
    data = {
        **body.model_dump(mode="json"),
        "organizer_id": request.state.user_id,
        "max_projects": PROJECT_SUBMISSION_LIMIT,
        "status": "draft",
    }
    result = db.table("hackathons").insert(data).execute()
    return HackathonResponse(**result.data[0])


@router.patch("/{hackathon_id}/status", response_model=HackathonResponse)
async def set_status(hackathon_id: str, body: HackathonUpdate, request: Request):
    """Organizer manually advances hackathon status (for dev/no-escrow flows)."""
    db = get_supabase_admin()
    _assert_organizer(db, hackathon_id, request.state.user_id)
    if not body.status:
        raise HTTPException(status_code=400, detail="status is required")
    if body.status.value != "completed":
        _assert_no_other_active_hackathon(db, exclude_id=hackathon_id)
    result = db.table("hackathons").update({"status": body.status}).eq("id", hackathon_id).execute()
    return HackathonResponse(**result.data[0])


@router.get("/{hackathon_id}/create-escrow-tx")
async def prepare_create_escrow(hackathon_id: str, request: Request):
    """Build the unsigned create_hackathon escrow transaction for the organizer to sign."""
    db = get_supabase_admin()
    hackathon = _assert_organizer(db, hackathon_id, request.state.user_id)
    if hackathon["status"] != "draft":
        raise HTTPException(status_code=400, detail="Escrow already set up for this hackathon")

    voting_start_ts = int(_parse_dt(hackathon["voting_start"]).timestamp())
    voting_end_ts = int(_parse_dt(hackathon["voting_end"]).timestamp())

    try:
        tx_b64, escrow_pda = await build_create_escrow_transaction(
            organizer_wallet=request.state.wallet_address,
            hackathon_id_str=hackathon_id,
            prize_usdc=hackathon["prize_pool_usdc"],
            voting_start_ts=voting_start_ts,
            voting_end_ts=voting_end_ts,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"transaction_b64": tx_b64, "escrow_pda": escrow_pda}


@router.patch("/{hackathon_id}/escrow", response_model=HackathonResponse)
async def set_escrow(hackathon_id: str, body: EscrowSetRequest, request: Request):
    """Called after organizer signs the create_hackathon tx and escrow is deployed."""
    db = get_supabase_admin()
    _assert_organizer(db, hackathon_id, request.state.user_id)
    result = db.table("hackathons").update({
        "escrow_pubkey": body.escrow_pubkey,
        "onchain_pda": body.onchain_pda,
        "status": "open",
    }).eq("id", hackathon_id).execute()
    return HackathonResponse(**result.data[0])


@router.get("/", response_model=List[HackathonResponse])
async def list_hackathons(
    status: Optional[HackathonStatus] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    db = get_supabase_admin()
    q = db.table("hackathons").select("*")
    if status:
        q = q.eq("status", status.value)
    result = q.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    hackathons = []
    for h in result.data:
        counts = db.table("projects").select("id", count="exact").eq("hackathon_id", h["id"]).execute()
        hackathons.append(HackathonResponse(**h, project_count=counts.count or 0))
    return hackathons


@router.get("/{hackathon_id}", response_model=HackathonResponse)
async def get_hackathon(hackathon_id: str):
    db = get_supabase_admin()
    result = db.table("hackathons").select("*").eq("id", hackathon_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Hackathon not found")
    return HackathonResponse(**result.data)


@router.get("/{hackathon_id}/leaderboard", response_model=List[LeaderboardEntry])
async def get_leaderboard(hackathon_id: str):
    db = get_supabase_admin()
    result = db.rpc("get_leaderboard", {"p_hackathon_id": hackathon_id}).execute()
    entries = []
    for row in result.data:
        project = ProjectResponse(
            id=row["id"],
            hackathon_id=row["hackathon_id"],
            team_lead_id=row["team_lead_id"],
            name=row["name"],
            description=row["description"],
            demo_url=row.get("demo_url"),
            repo_url=row.get("repo_url"),
            tech_stack=row.get("tech_stack", []),
            storage_asset_ids=row.get("storage_asset_ids", []),
            onchain_pda=row.get("onchain_pda"),
            status=row["status"],
            vote_count=row["vote_count"],
            created_at=row["created_at"],
        )
        entries.append(LeaderboardEntry(
            rank=row["rank"],
            project=project,
            total_votes=row["total_votes"],
            unique_voters=row["unique_voters"],
        ))
    return entries


@router.get("/{hackathon_id}/verify/refund/release-tx", response_model=ReleaseTxResponse)
@router.get("/{hackathon_id}/refund-tx", response_model=ReleaseTxResponse)
async def prepare_refund(hackathon_id: str, request: Request):
    """
    Build an unsigned release_prize transaction that refunds the organizer.
    This is only allowed after voting has ended and no projects were submitted.
    """
    db = get_supabase_admin()
    hackathon = _assert_organizer(db, hackathon_id, request.state.user_id)

    if hackathon["status"] in ("draft", "completed"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot refund when hackathon status is '{hackathon['status']}'",
        )
    if not _voting_has_ended(hackathon):
        raise HTTPException(status_code=400, detail="Cannot refund before voting has ended")
    if _project_count(db, hackathon_id) > 0:
        raise HTTPException(status_code=400, detail="Cannot refund because projects were submitted")
    if not hackathon.get("escrow_pubkey"):
        raise HTTPException(status_code=400, detail="Escrow not set up for this hackathon")

    tx_b64 = await build_refund_transaction(
        organizer_wallet=request.state.wallet_address,
        hackathon_id_str=hackathon_id,
        escrow_pda=hackathon["escrow_pubkey"],
    )

    return ReleaseTxResponse(
        transaction_b64=tx_b64,
        winner_wallet=request.state.wallet_address,
        prize_lamports=hackathon["prize_pool_usdc"],
    )


@router.post("/{hackathon_id}/verify/refund", response_model=HackathonResponse)
@router.post("/{hackathon_id}/refund", response_model=HackathonResponse)
async def verify_and_refund(
    hackathon_id: str,
    body: VerifyReleaseRequest,
    request: Request,
):
    """
    Organizer confirms a no-submissions refund after signing the release transaction.
    The escrow program uses the same release_prize instruction, with the organizer as recipient.
    """
    db = get_supabase_admin()
    hackathon = _assert_organizer(db, hackathon_id, request.state.user_id)

    if hackathon["status"] in ("draft", "completed"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot refund when hackathon status is '{hackathon['status']}'",
        )
    if not _voting_has_ended(hackathon):
        raise HTTPException(status_code=400, detail="Cannot refund before voting has ended")
    if _project_count(db, hackathon_id) > 0:
        raise HTTPException(status_code=400, detail="Cannot refund because projects were submitted")

    if hackathon.get("escrow_pubkey"):
        if not body.tx_signature:
            raise HTTPException(
                status_code=400,
                detail="tx_signature required — sign the refund transaction first",
            )
        verified = await verify_program_transaction_on_chain(
            body.tx_signature,
            request.state.wallet_address,
            [hackathon["escrow_pubkey"]],
        )
        if not verified:
            raise HTTPException(status_code=400, detail="Refund transaction not confirmed on-chain")

    result = db.table("hackathons").update({"status": "completed"}).eq("id", hackathon_id).execute()
    return HackathonResponse(**result.data[0])


@router.get("/{hackathon_id}/claim/{project_id}/tx", response_model=ClaimTxResponse)
async def prepare_claim(hackathon_id: str, project_id: str, request: Request):
    """Build an unsigned winner claim transaction certified by the backend."""
    db = get_supabase_admin()
    result = db.table("hackathons").select("*").eq("id", hackathon_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Hackathon not found")
    hackathon = result.data
    if hackathon["status"] in ("draft", "completed"):
        raise HTTPException(status_code=400, detail=f"Cannot claim prize when hackathon status is '{hackathon['status']}'")
    if not _voting_has_ended(hackathon):
        raise HTTPException(status_code=400, detail="Cannot claim before voting has ended")
    if not hackathon.get("escrow_pubkey"):
        raise HTTPException(status_code=400, detail="Escrow not set up for this hackathon")

    winner = _winning_project(db, hackathon_id)
    if not winner or winner["id"] != project_id:
        raise HTTPException(status_code=403, detail="Only the winning registered project can claim")
    if str(winner["team_lead_id"]) != request.state.user_id:
        raise HTTPException(status_code=403, detail="Only the winning team lead can claim")

    tx_b64, expires_at = await build_claim_prize_transaction(
        winner_wallet=request.state.wallet_address,
        hackathon_id_str=hackathon_id,
        escrow_pda=hackathon["escrow_pubkey"],
        project_id_str=project_id,
        prize_usdc=int(hackathon["prize_pool_usdc"]),
    )
    return ClaimTxResponse(
        transaction_b64=tx_b64,
        winner_wallet=request.state.wallet_address,
        prize_lamports=int(hackathon["prize_pool_usdc"]),
        expires_at=expires_at,
    )


@router.post("/{hackathon_id}/claim/{project_id}", response_model=HackathonResponse)
async def confirm_claim(
    hackathon_id: str,
    project_id: str,
    body: VerifyReleaseRequest,
    request: Request,
):
    """Confirm the winner's on-chain claim and mark the hackathon complete."""
    if not body.tx_signature:
        raise HTTPException(status_code=400, detail="tx_signature required")
    db = get_supabase_admin()
    result = db.table("hackathons").select("*").eq("id", hackathon_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Hackathon not found")
    hackathon = result.data
    winner = _winning_project(db, hackathon_id)
    if not winner or winner["id"] != project_id:
        raise HTTPException(status_code=403, detail="Only the winning registered project can claim")
    if str(winner["team_lead_id"]) != request.state.user_id:
        raise HTTPException(status_code=403, detail="Only the winning team lead can claim")

    verified = await verify_program_transaction_on_chain(
        body.tx_signature,
        request.state.wallet_address,
        [hackathon["escrow_pubkey"], winner["onchain_pda"]],
    )
    if not verified:
        raise HTTPException(status_code=400, detail="Claim transaction not confirmed on-chain")

    db.table("projects").update({"status": "winner"}).eq("id", project_id).execute()
    updated = db.table("hackathons").update({"status": "completed"}).eq("id", hackathon_id).execute()
    return HackathonResponse(**updated.data[0])


@router.get("/{hackathon_id}/verify/{project_id}/release-tx", response_model=ReleaseTxResponse)
async def prepare_release(hackathon_id: str, project_id: str, request: Request):
    raise HTTPException(status_code=410, detail="Organizer release is deprecated. Winner must claim the prize.")


@router.post("/{hackathon_id}/verify/{project_id}", response_model=HackathonResponse)
async def verify_and_release(
    hackathon_id: str,
    project_id: str,
    body: VerifyReleaseRequest,
    request: Request,
):
    """
    Organizer confirms the prize release after signing the transaction.
    If the hackathon has an on-chain escrow, tx_signature is required and verified.
    If no escrow is set (dev/test), DB state is updated without on-chain check.
    """
    raise HTTPException(status_code=410, detail="Organizer release is deprecated. Winner must claim the prize.")
    db = get_supabase_admin()
    hackathon = _assert_organizer(db, hackathon_id, request.state.user_id)

    if hackathon["status"] in ("draft", "completed"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot verify winner when hackathon status is '{hackathon['status']}'",
        )

    if hackathon.get("escrow_pubkey"):
        if not body.tx_signature:
            raise HTTPException(
                status_code=400,
                detail="tx_signature required — sign the release transaction first",
            )
        verified = await verify_release_on_chain(
            body.tx_signature,
            hackathon["escrow_pubkey"],
            request.state.wallet_address,
        )
        if not verified:
            raise HTTPException(status_code=400, detail="Release transaction not confirmed on-chain")

    db.table("projects").update({"status": "winner"}).eq("id", project_id).execute()
    result = db.table("hackathons").update({"status": "completed"}).eq("id", hackathon_id).execute()
    return HackathonResponse(**result.data[0])


def _assert_organizer(db, hackathon_id: str, user_id: str) -> dict:
    result = db.table("hackathons").select("*").eq("id", hackathon_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Hackathon not found")
    if str(result.data["organizer_id"]) != user_id:
        raise HTTPException(status_code=403, detail="Not the organizer")
    return result.data


def _winning_project(db, hackathon_id: str) -> dict | None:
    result = db.table("projects") \
        .select("id,team_lead_id,onchain_pda,vote_count,created_at") \
        .eq("hackathon_id", hackathon_id) \
        .in_("status", ["submitted", "approved", "winner"]) \
        .not_.is_("onchain_pda", "null") \
        .order("vote_count", desc=True) \
        .order("created_at") \
        .limit(1) \
        .maybe_single() \
        .execute()
    return result.data
