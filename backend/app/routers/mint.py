import logging

from fastapi import APIRouter, HTTPException, Request

from app.db import get_supabase_admin
from app.models.schemas import MintConfirmResponse
from app.services.solana_service import mint_builder_pass_server_side

router = APIRouter()
_log = logging.getLogger(__name__)


@router.post("/builder-pass/claim", response_model=MintConfirmResponse)
async def claim_builder_pass(request: Request):
    """
    Mint an Alpine Labs Builder Pass NFT directly to the caller's wallet.
    Fully server-side — no user transaction signing required.
    """
    db = get_supabase_admin()
    row = db.table("users").select("has_builder_pass").eq("id", request.state.user_id).maybe_single().execute()
    if row.data and row.data.get("has_builder_pass"):
        raise HTTPException(status_code=409, detail="Already owns a Builder Pass")

    try:
        tx_sig = await mint_builder_pass_server_side(request.state.wallet_address)
    except Exception as exc:
        _log.exception("Builder pass mint failed")
        raise HTTPException(status_code=500, detail=str(exc))

    db.table("users").update({"has_builder_pass": True}).eq("id", request.state.user_id).execute()
    _log.info("Builder pass granted to user %s tx=%s", request.state.user_id, tx_sig)

    return MintConfirmResponse(success=True, tx_signature=tx_sig)
