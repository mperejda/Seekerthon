"""
Recovery: mint a Support NFT for a payment that landed on-chain but was never
recorded because the backend errored before processing.

Usage:
    cd seekerthon   (repo root)
    python scripts/recover_support_nft_mint.py \\
        --payment-sig <TX_SIG> \\
        --buyer-wallet <WALLET> \\
        --builder-wallet <WALLET> \\
        --project-id <UUID> \\
        --hackathon-id <UUID> \\
        --buyer-user-id <UUID> \\
        --project-name "My Project" \\
        --price-raw 5000000 \\
        --treasury-bps 500 \\
        --api-base-url https://app.seekerthon.com

Requires backend/.env with the standard Seekerthon backend vars.
"""
import asyncio
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "backend", ".env"))


async def main(args) -> None:
    from app.services.solana_service import (
        verify_support_nft_payment,
        mint_support_cnft,
        fetch_confirmed_transaction,
        builder_pass_authority_pubkey,
        parse_wallet_sol_delta,
        fetch_sol_usd_price,
    )
    from app.db import get_supabase_admin

    db = get_supabase_admin()

    existing = db.table("support_nft_mints").select("id, status").eq("payment_tx_signature", args.payment_sig).limit(1).execute()
    if existing.data:
        row = existing.data[0]
        if row["status"] == "confirmed":
            print(f"Already confirmed (id={row['id']}). Nothing to do.")
            return
        print(f"Row exists with status={row['status']} — continuing to mint.")

    print(f"Verifying payment {args.payment_sig} ...")
    treasury_amount = args.price_raw * args.treasury_bps // 10000
    builder_amount = args.price_raw - treasury_amount
    tx_data = await verify_support_nft_payment(args.payment_sig, args.buyer_wallet, args.builder_wallet, args.price_raw, args.treasury_bps)
    print("Payment verified.")

    if not existing.data:
        db.table("support_nft_mints").insert({
            "user_id": args.buyer_user_id,
            "project_id": args.project_id,
            "hackathon_id": args.hackathon_id,
            "wallet_address": args.buyer_wallet,
            "builder_wallet": args.builder_wallet,
            "payment_tx_signature": args.payment_sig,
            "price_usdc_raw": args.price_raw,
            "treasury_amount_raw": treasury_amount,
            "builder_amount_raw": builder_amount,
            "status": "reconciled_error",
            "raw_transaction_json": {"payment_tx_signature": args.payment_sig, "payment_transaction": tx_data},
        }).execute()
        print("DB row reserved.")
    else:
        print("DB row already exists, skipping insert.")

    metadata_uri = f"{args.api_base_url}/api/v1/metadata/support/project/{args.project_id}"
    print(f"Minting cNFT to {args.buyer_wallet} ...")
    asset_id, mint_sig = await mint_support_cnft(args.buyer_wallet, metadata_uri, args.project_name)
    print(f"Minted! asset_id={asset_id}  mint_sig={mint_sig}")

    mint_cost = {
        "mint_sol_spent_lamports": None, "mint_sol_spent_usd": None,
        "sol_usd_price_at_mint": None, "sol_usd_price_source": None,
        "sol_usd_price_checked_at": None, "mint_transaction": None,
    }
    try:
        mint_tx_data = await fetch_confirmed_transaction(mint_sig)
        delta = parse_wallet_sol_delta(mint_tx_data, builder_pass_authority_pubkey())
        mint_cost["mint_sol_spent_lamports"] = max(-delta, 0)
        mint_cost["mint_transaction"] = mint_tx_data
    except Exception as e:
        print(f"Warning: could not calculate SOL spend: {e}")
    try:
        price = await fetch_sol_usd_price()
        mint_cost["sol_usd_price_at_mint"] = price["price_usd"]
        mint_cost["sol_usd_price_source"] = price["source"]
        mint_cost["sol_usd_price_checked_at"] = price["checked_at"]
        if mint_cost["mint_sol_spent_lamports"] is not None:
            mint_cost["mint_sol_spent_usd"] = (mint_cost["mint_sol_spent_lamports"] / 1e9) * price["price_usd"]
    except Exception as e:
        print(f"Warning: could not fetch SOL/USD price: {e}")

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
            "payment_tx_signature": args.payment_sig,
            "payment_transaction": tx_data,
            "mint_transaction": mint_cost["mint_transaction"],
        },
    }).eq("payment_tx_signature", args.payment_sig).execute()
    print("DB record updated to confirmed.")
    print(f"\nDone. Support NFT for '{args.project_name}' minted to {args.buyer_wallet}")
    print(f"  asset_id : {asset_id}")
    print(f"  mint_sig : {mint_sig}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Recover a Support NFT mint for a confirmed payment that was never processed")
    parser.add_argument("--payment-sig",    required=True, help="On-chain payment transaction signature")
    parser.add_argument("--buyer-wallet",   required=True, help="Buyer's Solana wallet address")
    parser.add_argument("--builder-wallet", required=True, help="Builder's Solana wallet address (receives payment minus treasury cut)")
    parser.add_argument("--project-id",     required=True, help="Project UUID")
    parser.add_argument("--hackathon-id",   required=True, help="Hackathon UUID")
    parser.add_argument("--buyer-user-id",  required=True, help="Buyer's user UUID from the users table")
    parser.add_argument("--project-name",   required=True, help="Project name (used in NFT metadata)")
    parser.add_argument("--price-raw",      required=True, type=int, help="Total price in USDC raw units (e.g. 5000000 = $5.00)")
    parser.add_argument("--treasury-bps",   required=True, type=int, help="Treasury fee in basis points (e.g. 500 = 5%%)")
    parser.add_argument("--api-base-url",   default="https://app.seekerthon.com", help="Base URL for metadata URIs")
    args = parser.parse_args()
    asyncio.run(main(args))
