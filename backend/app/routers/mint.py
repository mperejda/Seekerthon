import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import get_settings
from app.db import get_supabase_admin
from app.models.schemas import MintConfirmResponse
from app.services.solana_service import (
    builder_pass_authority_pubkey,
    build_usdc_transfer_transaction,
    fetch_confirmed_transaction,
    fetch_sol_usd_price,
    get_builder_pass_mint_availability,
    mint_nft_server_side,
    parse_wallet_sol_delta,
    parse_treasury_usdc_delta,
    submit_and_confirm_transaction,
    verify_usdc_payment,
)

router = APIRouter()
_log = logging.getLogger(__name__)
_settings = get_settings()


class PrepareResponse(BaseModel):
    transaction_b64: str
    mint_pubkey: str = ""
    amount_raw: int
    amount_display: str
    sol_fee_lamports: int = 0
    sol_fee_display: str = "0"


class ClaimRequest(BaseModel):
    signed_tx_b64: str
    mint_pubkey: str = ""


class BuilderPassStatusResponse(BaseModel):
    available: bool
    authority_balance_lamports: int
    min_required_lamports: int
    message: str


def _already_owns(user_id: str) -> bool:
    db = get_supabase_admin()
    row = db.table("users").select("has_builder_pass").eq("id", user_id).maybe_single().execute()
    return bool(row.data and row.data.get("has_builder_pass"))


async def _require_builder_pass_mint_available() -> dict:
    status = await get_builder_pass_mint_availability()
    if not status["available"]:
        raise HTTPException(status_code=503, detail="Builder Pass minting is temporarily unavailable")
    return status


@router.get("/builder-pass/status", response_model=BuilderPassStatusResponse)
async def builder_pass_status():
    try:
        return await get_builder_pass_mint_availability()
    except Exception:
        _log.exception("Failed to check Builder Pass mint availability")
        raise HTTPException(status_code=500, detail="Failed to check Builder Pass mint availability")


async def _builder_pass_mint_cost_snapshot(mint_sig: str) -> dict:
    snapshot = {
        "mint_sol_spent_lamports": None,
        "sol_usd_price_at_mint": None,
        "sol_usd_price_source": None,
        "sol_usd_price_checked_at": None,
        "mint_transaction": None,
    }

    try:
        mint_tx_data = await fetch_confirmed_transaction(mint_sig)
        authority_delta = parse_wallet_sol_delta(mint_tx_data, builder_pass_authority_pubkey())
        snapshot["mint_sol_spent_lamports"] = max(-authority_delta, 0)
        snapshot["mint_transaction"] = mint_tx_data
    except Exception:
        _log.exception("Failed to calculate Builder Pass SOL mint spend")

    try:
        price = await fetch_sol_usd_price()
        snapshot["sol_usd_price_at_mint"] = price["price_usd"]
        snapshot["sol_usd_price_source"] = price["source"]
        snapshot["sol_usd_price_checked_at"] = price["checked_at"]
    except Exception:
        _log.exception("Failed to fetch SOL/USD price for Builder Pass mint")

    return snapshot


@router.post("/builder-pass/prepare", response_model=PrepareResponse)
async def prepare_builder_pass_mint(request: Request):
    """
    Build a buyer-only payment transaction that Seeker can simulate cleanly.
    The buyer pays the USDC Builder Pass price; backend pays NFT mint costs.
    """
    if _already_owns(request.state.user_id):
        raise HTTPException(status_code=409, detail="Already owns a Builder Pass")

    price = _settings.builder_pass_price_usdc
    try:
        await _require_builder_pass_mint_available()
        tx_b64 = await build_usdc_transfer_transaction(request.state.wallet_address, price)
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("Failed to build Builder Pass payment transaction")
        raise HTTPException(status_code=500, detail=str(exc))

    return PrepareResponse(
        transaction_b64=tx_b64,
        amount_raw=price,
        amount_display=f"{price / 1_000_000:.6g}",
    )


@router.post("/builder-pass/claim", response_model=MintConfirmResponse)
async def claim_builder_pass(request: Request, body: ClaimRequest):
    """Submit the buyer payment, verify it, then mint the Builder Pass server-side."""
    if _already_owns(request.state.user_id):
        raise HTTPException(status_code=409, detail="Already owns a Builder Pass")

    db = get_supabase_admin()
    price = _settings.builder_pass_price_usdc
    try:
        await _require_builder_pass_mint_available()
        payment_sig = await submit_and_confirm_transaction(body.signed_tx_b64)
        tx_data = await verify_usdc_payment(payment_sig, request.state.wallet_address, price)
        if not tx_data:
            raise HTTPException(status_code=402, detail="USDC payment not confirmed on-chain")

        treasury_received = parse_treasury_usdc_delta(tx_data, _settings.builder_pass_treasury)
        if treasury_received < price:
            raise HTTPException(status_code=402, detail="Insufficient USDC payment")

        mint_pubkey, mint_sig = await mint_nft_server_side(request.state.wallet_address)
        mint_cost = await _builder_pass_mint_cost_snapshot(mint_sig)

        db.table("builder_pass_mints").insert(
            {
                "user_id": request.state.user_id,
                "wallet_address": request.state.wallet_address,
                "mint_pubkey": mint_pubkey,
                "mint_tx_signature": mint_sig,
                "price_usdc_raw": price,
                "treasury_usdc_received_raw": treasury_received,
                "mint_sol_spent_lamports": mint_cost["mint_sol_spent_lamports"],
                "sol_usd_price_at_mint": mint_cost["sol_usd_price_at_mint"],
                "sol_usd_price_source": mint_cost["sol_usd_price_source"],
                "sol_usd_price_checked_at": mint_cost["sol_usd_price_checked_at"],
                "status": "confirmed",
                "raw_transaction_json": {
                    "payment_tx_signature": payment_sig,
                    "payment_transaction": tx_data,
                    "mint_transaction": mint_cost["mint_transaction"],
                },
            }
        ).execute()

    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("Combined mint tx submission failed")
        raise HTTPException(status_code=500, detail=str(exc))

    db.table("users").update({"has_builder_pass": True}).eq("id", request.state.user_id).execute()
    _log.info("Builder pass granted to user %s mint=%s tx=%s", request.state.user_id, mint_pubkey, mint_sig)

    return MintConfirmResponse(success=True, tx_signature=mint_sig)
