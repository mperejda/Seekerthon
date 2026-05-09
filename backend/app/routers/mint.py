import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request

from app.db import get_supabase_admin
from app.models.schemas import MintConfirmRequest, MintConfirmResponse, MintPrepareResponse
from app.services.solana_service import (
    MAINNET_RPC_URL,
    _rpc_post,
    build_builder_pass_mint_transaction,
    verify_builder_pass_mint_on_chain,
)

router = APIRouter()
_log = logging.getLogger(__name__)


@router.post("/builder-pass/prepare", response_model=MintPrepareResponse)
async def prepare_builder_pass_mint(request: Request):
    """Build and partially-sign the builder pass mint transaction."""
    db = get_supabase_admin()
    row = db.table("users").select("has_builder_pass").eq("id", request.state.user_id).maybe_single().execute()
    if row.data and row.data.get("has_builder_pass"):
        raise HTTPException(status_code=409, detail="Already owns a Builder Pass")

    try:
        tx_b64, mint_address = await build_builder_pass_mint_transaction(request.state.wallet_address)
    except Exception as exc:
        _log.exception("Failed to build builder pass mint transaction")
        raise HTTPException(status_code=500, detail=str(exc))

    return MintPrepareResponse(transaction_b64=tx_b64, mint_address=mint_address)


@router.post("/builder-pass/confirm", response_model=MintConfirmResponse)
async def confirm_builder_pass_mint(request: Request, body: MintConfirmRequest):
    """Poll for the wallet-submitted mint tx and mark the user as a Builder Pass holder."""
    tx_sig = body.tx_signature
    _log.info("Confirming builder pass mint tx: %s", tx_sig)

    # Wallet already submitted — poll until confirmed (up to 60 s)
    for _ in range(60):
        await asyncio.sleep(1)
        confirm = await _rpc_post(
            "getTransaction",
            [tx_sig, {"commitment": "confirmed", "maxSupportedTransactionVersion": 0}],
            rpc_url=MAINNET_RPC_URL,
        )
        tx_data = confirm.get("result")
        if tx_data:
            if tx_data.get("meta", {}).get("err") is not None:
                raise HTTPException(status_code=400, detail="Transaction failed on-chain")
            break
    else:
        raise HTTPException(status_code=408, detail="Transaction confirmation timeout")

    if not await verify_builder_pass_mint_on_chain(tx_sig, request.state.wallet_address):
        raise HTTPException(status_code=400, detail="Transaction verification failed")

    db = get_supabase_admin()
    db.table("users").update({"has_builder_pass": True}).eq("id", request.state.user_id).execute()
    _log.info("Builder pass granted to user %s", request.state.user_id)

    return MintConfirmResponse(success=True, tx_signature=tx_sig)
