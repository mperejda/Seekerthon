"""
Airdrop SKR tokens equally to all wallets that cast at least one vote in a
hackathon. The full SKR balance of the airdrop wallet is distributed — load
it with exactly what you want to send and it all goes out with no dust.

Usage:
    cd seekerthon   (repo root)
    python scripts/airdrop_voter_skr.py <hackathon_id> --keypair <path.json> [--dry-run]

Examples:
    # Preview without sending
    python scripts/airdrop_voter_skr.py 189734d8-25ba-48a2-9a23-bb70e0262ee1 --keypair ~/airdrop-keypair.json --dry-run

    # Send for real
    python scripts/airdrop_voter_skr.py 189734d8-25ba-48a2-9a23-bb70e0262ee1 --keypair ~/airdrop-keypair.json

The keypair JSON file is a byte array in Phantom/Solana CLI format.
The airdrop wallet must hold SKR and enough SOL for transaction fees (~0.001 SOL per voter).

Requires backend/.env with:
    solana_mainnet_rpc_url
    skr_token_mint
    supabase_url + supabase_service_role_key
"""
import asyncio
import base64
import json
import os
import struct
import sys
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "backend", ".env"))

import httpx
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.instruction import Instruction, AccountMeta
from solders.hash import Hash
from solders.message import Message
from solders.transaction import Transaction

TOKEN_PROGRAM    = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ATA_PROGRAM      = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
SYSTEM_PROGRAM   = Pubkey.from_string("11111111111111111111111111111111")


def _find_ata(owner: Pubkey, mint: Pubkey) -> Pubkey:
    ata, _ = Pubkey.find_program_address(
        [bytes(owner), bytes(TOKEN_PROGRAM), bytes(mint)],
        ATA_PROGRAM,
    )
    return ata


async def _rpc(method: str, params: list, rpc_url: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        return r.json()


async def _get_decimals(mint: str, rpc_url: str) -> int:
    resp = await _rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}], rpc_url)
    return resp["result"]["value"]["data"]["parsed"]["info"]["decimals"]


async def _send_and_confirm(tx_b64: str, rpc_url: str) -> str:
    resp = await _rpc("sendTransaction", [tx_b64, {"encoding": "base64", "preflightCommitment": "confirmed"}], rpc_url)
    if "error" in resp:
        raise Exception(f"sendTransaction failed: {resp['error']}")
    sig = resp["result"]
    for _ in range(30):
        await asyncio.sleep(2)
        conf = await _rpc("getSignatureStatuses", [[sig], {"searchTransactionHistory": True}], rpc_url)
        status = ((conf.get("result") or {}).get("value") or [None])[0]
        if status:
            if status.get("err"):
                raise Exception(f"Transaction failed on-chain: {status['err']}")
            if status.get("confirmationStatus") in ("confirmed", "finalized"):
                return sig
    raise Exception("Transaction not confirmed within 60s")


async def _transfer_skr(
    authority_kp: Keypair,
    recipient: Pubkey,
    mint: Pubkey,
    amount_raw: int,
    rpc_url: str,
) -> str:
    """Send amount_raw SKR from authority to recipient, creating recipient ATA if needed."""
    src_ata = _find_ata(authority_kp.pubkey(), mint)
    dst_ata = _find_ata(recipient, mint)

    instructions = [
        # Idempotent ATA creation for recipient
        Instruction(
            program_id=ATA_PROGRAM,
            accounts=[
                AccountMeta(pubkey=authority_kp.pubkey(), is_signer=True, is_writable=True),
                AccountMeta(pubkey=dst_ata, is_signer=False, is_writable=True),
                AccountMeta(pubkey=recipient, is_signer=False, is_writable=False),
                AccountMeta(pubkey=mint, is_signer=False, is_writable=False),
                AccountMeta(pubkey=SYSTEM_PROGRAM, is_signer=False, is_writable=False),
                AccountMeta(pubkey=TOKEN_PROGRAM, is_signer=False, is_writable=False),
            ],
            data=bytes([1]),  # idempotent create
        ),
        # SPL Transfer
        Instruction(
            program_id=TOKEN_PROGRAM,
            accounts=[
                AccountMeta(pubkey=src_ata, is_signer=False, is_writable=True),
                AccountMeta(pubkey=dst_ata, is_signer=False, is_writable=True),
                AccountMeta(pubkey=authority_kp.pubkey(), is_signer=True, is_writable=False),
            ],
            data=bytes([3]) + struct.pack("<Q", amount_raw),
        ),
    ]

    bh = await _rpc("getLatestBlockhash", [{"commitment": "confirmed"}], rpc_url)
    blockhash = Hash.from_string(bh["result"]["value"]["blockhash"])
    msg = Message.new_with_blockhash(instructions, authority_kp.pubkey(), blockhash)
    tx = Transaction([authority_kp], msg, blockhash)
    tx_b64 = base64.b64encode(bytes(tx)).decode()
    return await _send_and_confirm(tx_b64, rpc_url)


async def _get_skr_balance(owner: Pubkey, mint: Pubkey, rpc_url: str) -> int:
    """Return raw SKR balance for owner, or 0 if ATA doesn't exist."""
    ata = _find_ata(owner, mint)
    resp = await _rpc("getTokenAccountBalance", [str(ata)], rpc_url)
    if resp.get("error") or not resp.get("result"):
        return 0
    return int(resp["result"]["value"]["amount"])


async def main(hackathon_id: str, keypair_path: str, dry_run: bool) -> None:
    from app.db import get_supabase_admin

    rpc_url  = os.environ["solana_mainnet_rpc_url"]
    skr_mint = os.environ["skr_token_mint"]
    mint_pk  = Pubkey.from_string(skr_mint)

    if keypair_path:
        with open(os.path.expanduser(keypair_path)) as f:
            airdrop_kp = Keypair.from_bytes(bytes(json.load(f)))
    else:
        airdrop_kp = Keypair.from_bytes(bytes(json.loads(os.environ["airdrop_keypair"])))

    db = get_supabase_admin()

    # Get all unique voters in this hackathon (any project, any vote)
    projects_res = db.table("projects").select("id").eq("hackathon_id", hackathon_id).execute()
    project_ids = [p["id"] for p in (projects_res.data or [])]
    if not project_ids:
        print("No projects found for this hackathon.")
        return

    votes_res = db.table("votes").select("voter_id").in_("project_id", project_ids).execute()
    voter_ids = list({v["voter_id"] for v in (votes_res.data or [])})
    if not voter_ids:
        print("No voters found for this hackathon.")
        return

    # Resolve wallet addresses
    users_res = db.table("users").select("id, wallet_address").in_("id", voter_ids).execute()
    wallets = {u["id"]: u["wallet_address"] for u in (users_res.data or []) if u.get("wallet_address")}
    missing = len(voter_ids) - len(wallets)
    if missing:
        print(f"Warning: {missing} voter(s) have no wallet address, skipping.")

    recipients = list(wallets.values())
    if not recipients:
        print("No valid recipient wallets.")
        return

    # Read full SKR balance of airdrop wallet — distribute it all
    decimals = await _get_decimals(skr_mint, rpc_url)
    total_raw = await _get_skr_balance(airdrop_kp.pubkey(), mint_pk, rpc_url)
    if total_raw == 0:
        print(f"Airdrop wallet {airdrop_kp.pubkey()} has no SKR balance.")
        return

    per_voter_raw = total_raw // len(recipients)
    per_voter_skr = per_voter_raw / (10 ** decimals)
    total_skr = total_raw / (10 ** decimals)

    print(f"Hackathon    : {hackathon_id}")
    print(f"Airdrop wallet: {airdrop_kp.pubkey()}")
    print(f"SKR balance  : {total_skr:.6f} SKR")
    print(f"Voters       : {len(recipients)}")
    print(f"Per voter    : {per_voter_skr:.6f} SKR ({per_voter_raw} raw)")
    dust = total_raw - (per_voter_raw * len(recipients))
    if dust:
        print(f"Dust         : {dust} raw (stays in airdrop wallet)")

    if dry_run:
        print("\n--- DRY RUN — no transactions sent ---")
        for w in recipients:
            print(f"  -> {w}  {per_voter_skr:.6f} SKR")
        return

    print("\nSending airdrops...")
    failed = []
    for wallet in recipients:
        for attempt in range(3):
            try:
                recipient_pk = Pubkey.from_string(wallet)
                sig = await _transfer_skr(airdrop_kp, recipient_pk, mint_pk, per_voter_raw, rpc_url)
                print(f"  OK {wallet}  sig={sig}")
                break
            except Exception as e:
                if attempt < 2:
                    print(f"  RETRY {wallet}  ({e})")
                    await asyncio.sleep(5)
                else:
                    print(f"  FAIL {wallet}  ERROR: {e}")
                    failed.append(wallet)
    if failed:
        print(f"\nFailed wallets ({len(failed)}):")
        for w in failed:
            print(f"  {w}")

    print("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Airdrop SKR to all voters in a hackathon")
    parser.add_argument("hackathon_id", help="UUID of the completed hackathon")
    parser.add_argument("--keypair", default=None, help="Path to airdrop wallet keypair JSON (falls back to airdrop_keypair env var)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending")
    args = parser.parse_args()
    asyncio.run(main(args.hackathon_id, args.keypair, args.dry_run))
