import uuid as uuid_module
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request
from app.constants import REGISTRATION_LIMIT
from app.config import get_settings
from app.db import get_supabase_admin
from app.models.schemas import (
    HackathonRegistrationResponse,
    RegistrationConfirmRequest,
    RegistrationPrepareResponse,
    RegistrationStatusResponse,
)
from app.services.solana_service import (
    build_register_project_transaction,
    derive_project_record_pda,
    verify_registration_fee_payment_on_chain,
    verify_program_transaction_on_chain,
)

router = APIRouter()


def _check_registration_open(h: dict) -> None:
    if h["status"] != "open":
        raise HTTPException(status_code=400, detail="Hackathon is not open for registration")
    voting_start = datetime.fromisoformat(h["voting_start"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) >= voting_start:
        raise HTTPException(status_code=400, detail="Registration is closed — voting has started")


def _check_not_already_registered(db, hackathon_id: str, user_id: str) -> None:
    existing = db.table("hackathon_registrations").select("id") \
        .eq("hackathon_id", hackathon_id) \
        .eq("user_id", user_id) \
        .execute()
    if existing.data:
        raise HTTPException(status_code=409, detail="You are already registered for this hackathon")


def _check_spots_available(db, hackathon_id: str) -> None:
    count_res = db.table("hackathon_registrations").select("id", count="exact") \
        .eq("hackathon_id", hackathon_id) \
        .execute()
    if (count_res.count or 0) >= REGISTRATION_LIMIT:
        raise HTTPException(
            status_code=409,
            detail=f"Hackathon is full — all {REGISTRATION_LIMIT} spots are taken",
        )


@router.get("/{hackathon_id}/register-tx", response_model=RegistrationPrepareResponse)
async def prepare_registration(hackathon_id: str, request: Request):
    """
    Prepare a registration transaction.
    Returns a pre-generated project_id and, if the hackathon has an on-chain escrow,
    an unsigned register_project transaction for the user to sign.
    For no-escrow hackathons transaction_b64 is null — call POST /register directly.
    """
    db = get_supabase_admin()
    hackathon = db.table("hackathons").select("*").eq("id", hackathon_id).single().execute()
    if not hackathon.data:
        raise HTTPException(status_code=404, detail="Hackathon not found")
    h = hackathon.data

    _check_registration_open(h)
    _check_not_already_registered(db, hackathon_id, request.state.user_id)
    _check_spots_available(db, hackathon_id)

    project_id = str(uuid_module.uuid4())

    if h.get("escrow_pubkey"):
        tx_b64, project_record_pda = await build_register_project_transaction(
            request.state.wallet_address,
            h["escrow_pubkey"],
            project_id,
        )
        return RegistrationPrepareResponse(
            transaction_b64=tx_b64,
            project_id=project_id,
            project_record_pda=project_record_pda,
        )

    return RegistrationPrepareResponse(project_id=project_id)


@router.post("/{hackathon_id}/register", response_model=HackathonRegistrationResponse, status_code=201)
async def confirm_registration(hackathon_id: str, body: RegistrationConfirmRequest, request: Request):
    """
    Confirm hackathon registration.

    If the hackathon has an on-chain escrow, tx_signature is required and must be the
    signed register_project transaction returned by GET /register-tx.  The backend
    verifies the transaction landed on-chain before creating the DB records.

    On success this atomically creates:
      - a hackathon_registrations row (the spot reservation)
      - a projects row with status='registered' and onchain_pda set (or null for no-escrow)
    The team must then call PATCH /projects/{id}/submit to fill in project details.
    """
    db = get_supabase_admin()
    hackathon = db.table("hackathons").select("*").eq("id", hackathon_id).single().execute()
    if not hackathon.data:
        raise HTTPException(status_code=404, detail="Hackathon not found")
    h = hackathon.data

    _check_registration_open(h)
    _check_not_already_registered(db, hackathon_id, request.state.user_id)
    _check_spots_available(db, hackathon_id)

    project_id = body.project_id
    onchain_pda: str | None = None

    if h.get("escrow_pubkey"):
        if not body.tx_signature:
            raise HTTPException(status_code=400, detail="tx_signature required for escrow hackathons")

        project_record_pda = derive_project_record_pda(h["escrow_pubkey"], project_id)
        verified = await verify_program_transaction_on_chain(
            body.tx_signature,
            request.state.wallet_address,
            [h["escrow_pubkey"], project_record_pda],
            "register_project",
        )
        if not verified:
            raise HTTPException(
                status_code=400,
                detail="Registration transaction not confirmed on-chain",
            )
        fee = get_settings().registration_fee_usdc
        if fee > 0:
            paid = await verify_registration_fee_payment_on_chain(
                body.tx_signature,
                request.state.wallet_address,
                fee,
            )
            if not paid:
                raise HTTPException(status_code=402, detail="Registration fee payment not confirmed on-chain")
        onchain_pda = project_record_pda

    user = db.table("users").select("wallet_address").eq("id", request.state.user_id).single().execute()
    if not user.data:
        raise HTTPException(status_code=404, detail="User not found")

    # Create the project stub first so we can FK-reference it from the registration row.
    project_data = {
        "id": project_id,
        "hackathon_id": hackathon_id,
        "team_lead_id": request.state.user_id,
        "name": "",
        "description": "",
        "status": "registered",
        "onchain_pda": onchain_pda,
    }
    project_res = db.table("projects").insert(project_data).execute()
    if not project_res.data:
        raise HTTPException(status_code=500, detail="Failed to create project record")

    reg_data = {
        "hackathon_id": hackathon_id,
        "user_id": request.state.user_id,
        "wallet_address": user.data["wallet_address"],
        "project_id": project_id,
    }
    reg_res = db.table("hackathon_registrations").insert(reg_data).execute()

    if body.tx_signature and h.get("escrow_pubkey"):
        fee = get_settings().registration_fee_usdc
        if fee > 0:
            db.table("registration_fees").insert({
                "hackathon_id": hackathon_id,
                "project_id": project_id,
                "user_id": request.state.user_id,
                "wallet_address": user.data["wallet_address"],
                "tx_signature": body.tx_signature,
                "amount_usdc": fee,
                "amount_usd": fee / 1_000_000,
            }).execute()

    return HackathonRegistrationResponse(**reg_res.data[0])


@router.get("/{hackathon_id}/registration", response_model=RegistrationStatusResponse)
async def get_registration_status(hackathon_id: str, request: Request):
    """
    Returns spot availability.  When the caller is authenticated their registration
    status is also included.  Public: all GETs under /api/v1/hackathons are auth-exempt.
    """
    db = get_supabase_admin()
    hackathon = db.table("hackathons").select("id").eq("id", hackathon_id).single().execute()
    if not hackathon.data:
        raise HTTPException(status_code=404, detail="Hackathon not found")

    count_res = db.table("hackathon_registrations").select("id", count="exact") \
        .eq("hackathon_id", hackathon_id) \
        .execute()
    spots_taken = count_res.count or 0

    user_id = getattr(request.state, "user_id", None)
    reg_obj = None
    is_registered = False

    if user_id:
        my_reg = db.table("hackathon_registrations").select("*") \
            .eq("hackathon_id", hackathon_id) \
            .eq("user_id", user_id) \
            .limit(1) \
            .execute()
        if my_reg.data:
            is_registered = True
            reg_obj = HackathonRegistrationResponse(**my_reg.data[0])

    return RegistrationStatusResponse(
        is_registered=is_registered,
        registration=reg_obj,
        spots_taken=spots_taken,
        spots_remaining=max(0, REGISTRATION_LIMIT - spots_taken),
        spots_total=REGISTRATION_LIMIT,
    )
