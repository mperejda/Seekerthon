import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import get_settings
from app.db import get_supabase_admin
from app.models.schemas import MintConfirmResponse
from app.services.solana_service import (
    build_partial_signed_mint_transaction,
    fetch_confirmed_transaction,
    parse_treasury_usdc_delta,
    submit_mint_transaction,
    validate_builder_pass_mint_transaction,
)

router = APIRouter()
_log = logging.getLogger(__name__)
_settings = get_settings()


class PrepareResponse(BaseModel):
    transaction_b64: str
    mint_pubkey: str
    amount_raw: int
    amount_display: str
    sol_fee_lamports: int
    sol_fee_display: str


class ClaimRequest(BaseModel):
    signed_tx_b64: str
    mint_pubkey: str


def _already_owns(user_id: str) -> bool:
    db = get_supabase_admin()
    row = db.table("users").select("has_builder_pass").eq("id", user_id).maybe_single().execute()
    return bool(row.data and row.data.get("has_builder_pass"))


def _mint_ledger_row(db, mint_pubkey: str, mint_tx_signature: str) -> dict | None:
    by_sig = (
        db.table("builder_pass_mints")
        .select("status,user_id,wallet_address")
        .eq("mint_tx_signature", mint_tx_signature)
        .maybe_single()
        .execute()
    )
    if by_sig is not None and by_sig.data:
        return by_sig.data

    by_mint = (
        db.table("builder_pass_mints")
        .select("status,user_id,wallet_address")
        .eq("mint_pubkey", mint_pubkey)
        .maybe_single()
        .execute()
    )
    if by_mint is not None and by_mint.data:
        return by_mint.data
    return None


@router.post("/builder-pass/prepare", response_model=PrepareResponse)
async def prepare_builder_pass_mint(request: Request):
    """
    Build and return a partially-signed combined transaction (payment + NFT mint).
    The buyer's wallet must add the final signature; submission happens in /claim.
    Atomic: either payment AND NFT land, or neither does.
    """
    if _already_owns(request.state.user_id):
        raise HTTPException(status_code=409, detail="Already owns a Builder Pass")

    price = _settings.builder_pass_price_usdc
    try:
        tx_b64, mint_pubkey, amount_raw, amount_display, sol_fee, sol_fee_display = \
            await build_partial_signed_mint_transaction(request.state.wallet_address, price)
    except Exception as exc:
        _log.exception("Failed to build combined mint transaction")
        raise HTTPException(status_code=500, detail=str(exc))

    return PrepareResponse(
        transaction_b64=tx_b64,
        mint_pubkey=mint_pubkey,
        amount_raw=amount_raw,
        amount_display=amount_display,
        sol_fee_lamports=sol_fee,
        sol_fee_display=sol_fee_display,
    )


@router.post("/builder-pass/claim", response_model=MintConfirmResponse)
async def claim_builder_pass(request: Request, body: ClaimRequest):
    """Submit the buyer-signed combined tx. Payment and NFT mint confirm atomically."""
    if _already_owns(request.state.user_id):
        raise HTTPException(status_code=409, detail="Already owns a Builder Pass")

    db = get_supabase_admin()
    try:
        mint_sig = await submit_mint_transaction(body.signed_tx_b64, body.mint_pubkey)
        existing_row = _mint_ledger_row(db, body.mint_pubkey, mint_sig)
        if (
            existing_row
            and existing_row.get("status") == "confirmed"
            and str(existing_row.get("user_id")) == str(request.state.user_id)
            and existing_row.get("wallet_address") == request.state.wallet_address
        ):
            db.table("users").update({"has_builder_pass": True}).eq("id", request.state.user_id).execute()
            return MintConfirmResponse(success=True, tx_signature=mint_sig)
        if existing_row is not None:
            raise HTTPException(status_code=409, detail="Builder Pass mint requires manual reconciliation")

        tx_data = await fetch_confirmed_transaction(mint_sig)
        treasury_received = parse_treasury_usdc_delta(tx_data, _settings.builder_pass_treasury)
        expected_price = _settings.builder_pass_price_usdc
        is_valid_mint, validation_error = validate_builder_pass_mint_transaction(
            tx_data,
            request.state.wallet_address,
            body.mint_pubkey,
            expected_price,
            _settings.builder_pass_treasury,
        )
        status = "confirmed" if is_valid_mint else "reconciled_error"

        db.table("builder_pass_mints").insert(
            {
                "user_id": request.state.user_id,
                "wallet_address": request.state.wallet_address,
                "mint_pubkey": body.mint_pubkey,
                "mint_tx_signature": mint_sig,
                "price_usdc_raw": expected_price,
                "treasury_usdc_received_raw": treasury_received,
                "status": status,
                "raw_transaction_json": tx_data,
            }
        ).execute()

        if status != "confirmed":
            raise HTTPException(
                status_code=409,
                detail=f"Builder Pass mint requires manual reconciliation: {validation_error}",
            )
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("Combined mint tx submission failed")
        raise HTTPException(status_code=500, detail=str(exc))

    db.table("users").update({"has_builder_pass": True}).eq("id", request.state.user_id).execute()
    _log.info("Builder pass granted to user %s mint=%s tx=%s", request.state.user_id, body.mint_pubkey, mint_sig)

    return MintConfirmResponse(success=True, tx_signature=mint_sig)
