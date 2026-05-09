import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import get_settings
from app.db import get_supabase_admin
from app.models.schemas import MintConfirmResponse
from app.services.solana_service import (
    build_usdc_transfer_transaction,
    mint_builder_pass_server_side,
    submit_and_confirm_transaction,
    verify_usdc_payment,
)

router = APIRouter()
_log = logging.getLogger(__name__)
_settings = get_settings()


class PrepareResponse(BaseModel):
    transaction_b64: str       # unsigned payment tx for the wallet to sign
    amount_raw: int            # raw USDC units (6 decimals)
    amount_display: str        # human-readable USDC e.g. "0.01"
    sol_fee_lamports: int      # SOL sent to authority to cover NFT mint costs
    sol_fee_display: str       # human-readable SOL e.g. "0.025"


class ClaimRequest(BaseModel):
    signed_tx_b64: str     # wallet-signed USDC transfer tx (base64); backend submits it


def _already_owns(user_id: str) -> bool:
    db = get_supabase_admin()
    row = db.table("users").select("has_builder_pass").eq("id", user_id).maybe_single().execute()
    return bool(row.data and row.data.get("has_builder_pass"))


@router.post("/builder-pass/prepare", response_model=PrepareResponse)
async def prepare_builder_pass_mint(request: Request):
    """Return an unsigned USDC transfer transaction for the wallet to sign and send."""
    if _already_owns(request.state.user_id):
        raise HTTPException(status_code=409, detail="Already owns a Builder Pass")

    price = _settings.builder_pass_price_usdc
    try:
        tx_b64 = await build_usdc_transfer_transaction(request.state.wallet_address, price)
    except Exception as exc:
        _log.exception("Failed to build USDC transfer transaction")
        raise HTTPException(status_code=500, detail=str(exc))

    sol_fee = _settings.builder_pass_sol_fee_lamports
    return PrepareResponse(
        transaction_b64=tx_b64,
        amount_raw=price,
        amount_display=f"{price / 1_000_000:.6g}",
        sol_fee_lamports=sol_fee,
        sol_fee_display=f"{sol_fee / 1_000_000_000:.6g}",
    )


@router.post("/builder-pass/claim", response_model=MintConfirmResponse)
async def claim_builder_pass(request: Request, body: ClaimRequest):
    """Verify USDC payment then mint the Builder Pass NFT server-side."""
    if _already_owns(request.state.user_id):
        raise HTTPException(status_code=409, detail="Already owns a Builder Pass")

    price = _settings.builder_pass_price_usdc

    # Skip payment when price is 0; otherwise backend submits the signed tx and verifies
    if price > 0:
        try:
            tx_sig = await submit_and_confirm_transaction(body.signed_tx_b64)
        except Exception as exc:
            _log.exception("USDC payment submission failed")
            raise HTTPException(status_code=402, detail=f"Payment transaction failed: {exc}")
        paid = await verify_usdc_payment(tx_sig, request.state.wallet_address, price)
        if not paid:
            raise HTTPException(status_code=402, detail="USDC payment not confirmed")

    try:
        mint_sig = await mint_builder_pass_server_side(request.state.wallet_address)
    except Exception as exc:
        _log.exception("Builder pass mint failed")
        raise HTTPException(status_code=500, detail=str(exc))

    db = get_supabase_admin()
    db.table("users").update({"has_builder_pass": True}).eq("id", request.state.user_id).execute()
    _log.info("Builder pass granted to user %s mint_tx=%s", request.state.user_id, mint_sig)

    return MintConfirmResponse(success=True, tx_signature=mint_sig)
