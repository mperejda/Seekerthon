import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import get_supabase_admin
from app.models.schemas import (
    SupportNftClaimRequest,
    SupportNftClaimResponse,
    SupportNftMineResponse,
    SupportNftPrepareRequest,
    SupportNftPrepareResponse,
)
from app.services.solana_service import (
    build_support_nft_payment_transaction,
    fetch_sol_usd_price,
    mint_support_cnft,
    parse_wallet_sol_delta,
    fetch_confirmed_transaction,
    submit_and_confirm_transaction,
    verify_support_nft_payment,
)

router = APIRouter()
_log = logging.getLogger(__name__)
_settings = get_settings()

_APPROVED_PROJECT_STATUSES = ("approved", "winner")


def _get_project_and_hackathon(project_id: str) -> tuple[dict, dict]:
    db = get_supabase_admin()
    proj_res = db.table("projects").select("*").eq("id", project_id).maybe_single().execute()
    if not proj_res.data:
        raise HTTPException(status_code=404, detail="Project not found")
    project = proj_res.data
    if project["status"] not in _APPROVED_PROJECT_STATUSES:
        raise HTTPException(status_code=400, detail="Project is not eligible for support NFT minting")

    hack_res = db.table("hackathons").select("*").eq("id", project["hackathon_id"]).maybe_single().execute()
    if not hack_res.data:
        raise HTTPException(status_code=404, detail="Hackathon not found")
    hackathon = hack_res.data
    if hackathon["status"] != "completed":
        raise HTTPException(status_code=400, detail="Hackathon is not yet completed")

    return project, hackathon


def _get_builder_wallet(team_lead_id: str) -> str:
    db = get_supabase_admin()
    user_res = db.table("users").select("wallet_address").eq("id", team_lead_id).maybe_single().execute()
    if not user_res.data or not user_res.data.get("wallet_address"):
        raise HTTPException(status_code=400, detail="Builder wallet address not found")
    return user_res.data["wallet_address"]


async def _support_nft_mint_cost_snapshot(mint_sig: str) -> dict:
    """Capture authority SOL spend and SOL/USD price at mint time for accounting."""
    from app.services.solana_service import MAINNET_RPC_URL
    snapshot = {
        "mint_sol_spent_lamports": None,
        "mint_sol_spent_usd": None,
        "sol_usd_price_at_mint": None,
        "sol_usd_price_source": None,
        "sol_usd_price_checked_at": None,
        "mint_transaction": None,
    }
    from app.services.solana_service import builder_pass_authority_pubkey
    try:
        mint_tx_data = await fetch_confirmed_transaction(mint_sig)
        authority_delta = parse_wallet_sol_delta(mint_tx_data, builder_pass_authority_pubkey())
        snapshot["mint_sol_spent_lamports"] = max(-authority_delta, 0)
        snapshot["mint_transaction"] = mint_tx_data
    except Exception:
        _log.exception("Failed to calculate Support NFT SOL mint spend")
    try:
        price = await fetch_sol_usd_price()
        snapshot["sol_usd_price_at_mint"] = price["price_usd"]
        snapshot["sol_usd_price_source"] = price["source"]
        snapshot["sol_usd_price_checked_at"] = price["checked_at"]
        lamports = snapshot["mint_sol_spent_lamports"]
        if lamports is not None:
            snapshot["mint_sol_spent_usd"] = (lamports / 1_000_000_000) * price["price_usd"]
    except Exception:
        _log.exception("Failed to fetch SOL/USD price for Support NFT mint")
    return snapshot


@router.get("/metadata/support/project/{project_id}")
async def support_nft_metadata(project_id: str):
    """Public endpoint — returns Metaplex-compatible metadata JSON for a support NFT."""
    db = get_supabase_admin()
    proj_res = db.table("projects").select("name, description, tech_stack, hackathon_id").eq("id", project_id).maybe_single().execute()
    if not proj_res.data:
        raise HTTPException(status_code=404, detail="Project not found")
    project = proj_res.data

    hack_res = db.table("hackathons").select("title").eq("id", project["hackathon_id"]).maybe_single().execute()
    hackathon_title = hack_res.data["title"] if hack_res.data else "Seekerthon"

    tech_stack = project.get("tech_stack") or []
    tech_stack_str = ", ".join(tech_stack) if tech_stack else "Solana"

    return JSONResponse({
        "name": f"Builder Support: {project['name']}",
        "symbol": "BSUP",
        "description": f"I supported {project['name']} at {hackathon_title}",
        "image": _settings.support_nft_image_uri,
        "attributes": [
            {"trait_type": "Hackathon", "value": hackathon_title},
            {"trait_type": "Project", "value": project["name"]},
            {"trait_type": "Tech Stack", "value": tech_stack_str},
        ],
    })


@router.post("/prepare", response_model=SupportNftPrepareResponse)
async def prepare_support_nft(request: Request, body: SupportNftPrepareRequest):
    """Build an unsigned USDC split-payment transaction for minting a Builder Support NFT."""
    project_id = str(body.project_id)
    buyer_wallet = request.state.wallet_address
    _log.info("Support NFT prepare: project=%s buyer=%s", project_id, buyer_wallet)

    project, _ = _get_project_and_hackathon(project_id)
    builder_wallet = _get_builder_wallet(project["team_lead_id"])

    db = get_supabase_admin()
    existing = db.table("support_nft_mints").select("id").eq("wallet_address", buyer_wallet).eq("project_id", project_id).maybe_single().execute()
    if existing.data:
        raise HTTPException(status_code=409, detail="Already minted a Support NFT for this project")

    price = _settings.support_nft_price_usdc
    bps = _settings.support_nft_treasury_bps
    treasury_amount = price * bps // 10000
    builder_amount = price - treasury_amount

    try:
        tx_b64 = await build_support_nft_payment_transaction(buyer_wallet, builder_wallet, price, bps)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("Failed to build Support NFT payment transaction")
        raise HTTPException(status_code=500, detail=str(exc))

    return SupportNftPrepareResponse(
        transaction_b64=tx_b64,
        amount_display=f"${price / 1_000_000:.2f} USDC",
        treasury_amount_display=f"${treasury_amount / 1_000_000:.2f} USDC",
        builder_amount_display=f"${builder_amount / 1_000_000:.2f} USDC",
        project_name=project["name"],
        project_id=project_id,
    )


@router.post("/claim", response_model=SupportNftClaimResponse)
async def claim_support_nft(request: Request, body: SupportNftClaimRequest):
    """Submit the signed payment tx, verify it, then mint the cNFT server-side."""
    project_id = str(body.project_id)
    buyer_wallet = request.state.wallet_address
    _log.info("Support NFT claim: project=%s buyer=%s", project_id, buyer_wallet)

    project, hackathon = _get_project_and_hackathon(project_id)
    builder_wallet = _get_builder_wallet(project["team_lead_id"])

    db = get_supabase_admin()
    price = _settings.support_nft_price_usdc
    bps = _settings.support_nft_treasury_bps

    try:
        payment_sig = await submit_and_confirm_transaction(body.signed_tx_b64)

        # Idempotency: if we already processed this payment, return existing mint
        existing = db.table("support_nft_mints").select("*").eq("payment_tx_signature", payment_sig).maybe_single().execute()
        if existing.data:
            row = existing.data
            if row["wallet_address"] != buyer_wallet:
                raise HTTPException(status_code=409, detail="Payment already used by another account")
            _log.info("Support NFT claim retry — reusing existing mint for payment=%s", payment_sig)
            return SupportNftClaimResponse(success=True, tx_signature=row["mint_tx_signature"] or payment_sig)

        tx_data = await verify_support_nft_payment(payment_sig, buyer_wallet, builder_wallet, price, bps)
        treasury_amount = price * bps // 10000
        builder_amount = price - treasury_amount

        # Reserve payment signature before on-chain mint (crash-safety gate)
        db.table("support_nft_mints").insert({
            "user_id": request.state.user_id,
            "project_id": project_id,
            "hackathon_id": project["hackathon_id"],
            "wallet_address": buyer_wallet,
            "builder_wallet": builder_wallet,
            "payment_tx_signature": payment_sig,
            "price_usdc_raw": price,
            "treasury_amount_raw": treasury_amount,
            "builder_amount_raw": builder_amount,
            "status": "reconciled_error",
            "raw_transaction_json": {"payment_tx_signature": payment_sig, "payment_transaction": tx_data},
        }).execute()

        metadata_uri = f"{_settings.api_base_url}/api/v1/metadata/support/project/{project_id}"
        asset_id, mint_sig = await mint_support_cnft(buyer_wallet, metadata_uri, project["name"])
        mint_cost = await _support_nft_mint_cost_snapshot(mint_sig)

        db.table("support_nft_mints").update({
            "asset_id": asset_id,
            "mint_tx_signature": mint_sig,
            "mint_sol_spent_lamports": mint_cost["mint_sol_spent_lamports"],
            "mint_sol_spent_usd": mint_cost["mint_sol_spent_usd"],
            "sol_usd_price_at_mint": mint_cost["sol_usd_price_at_mint"],
            "sol_usd_price_source": mint_cost["sol_usd_price_source"],
            "sol_usd_price_checked_at": mint_cost["sol_usd_price_checked_at"],
            "status": "confirmed",
            "raw_transaction_json": {
                "payment_tx_signature": payment_sig,
                "payment_transaction": tx_data,
                "mint_transaction": mint_cost["mint_transaction"],
            },
        }).eq("payment_tx_signature", payment_sig).execute()

    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.exception("Support NFT claim failed for project=%s buyer=%s", project_id, buyer_wallet)
        raise HTTPException(status_code=500, detail=str(exc))

    _log.info("Support NFT minted: project=%s buyer=%s asset_id=%s mint_sig=%s", project_id, buyer_wallet, asset_id, mint_sig)
    return SupportNftClaimResponse(success=True, tx_signature=mint_sig)


@router.get("/mine", response_model=SupportNftMineResponse)
async def support_nft_mine(request: Request, hackathon_id: str):
    """Return project IDs the caller has minted Support NFTs for in the given hackathon."""
    db = get_supabase_admin()
    rows = (
        db.table("support_nft_mints")
        .select("project_id")
        .eq("wallet_address", request.state.wallet_address)
        .eq("hackathon_id", hackathon_id)
        .eq("status", "confirmed")
        .execute()
    )
    project_ids = [str(r["project_id"]) for r in (rows.data or [])]
    return SupportNftMineResponse(project_ids=project_ids)
