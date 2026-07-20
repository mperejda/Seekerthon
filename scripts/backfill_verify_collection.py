"""
One-time script to add creator verification and 5% royalties to all existing
Builder Pass NFTs, and re-verify their collection membership.

Why: NFTs were minted without a creator field or royalties, causing wallets
to flag them as incomplete/spam. This script sends UpdateMetadataAccountV2
+ VerifySizedCollectionItem for each existing mint.

Usage:
    cd seekerthon   (repo root)
    python scripts/backfill_verify_collection.py

Requires backend/.env with:
    builder_pass_authority_keypair
    builder_pass_collection_mint
    builder_pass_metadata_uri
    solana_mainnet_rpc_url
    supabase_url
    supabase_service_role_key
"""
import asyncio
import base64
import json
import os
import struct

import httpx
from dotenv import load_dotenv
from supabase import create_client
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.hash import Hash
from solders.instruction import Instruction, AccountMeta
from solders.message import Message
from solders.transaction import Transaction

load_dotenv(os.path.join(os.path.dirname(__file__), "../backend/.env"))

METADATA_PROGRAM_ID = Pubkey.from_string("metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s")
SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")


def _env(key: str) -> str:
    return os.environ.get(key) or os.environ[key.upper()]


RPC_URL = _env("solana_mainnet_rpc_url")
AUTHORITY_KEYPAIR_JSON = _env("builder_pass_authority_keypair")
COLLECTION_MINT = _env("builder_pass_collection_mint")
METADATA_URI = _env("builder_pass_metadata_uri")
SUPABASE_URL = _env("supabase_url")
SUPABASE_KEY = _env("supabase_service_role_key")


def _borsh_str(s: str) -> bytes:
    enc = s.encode("utf-8")
    return struct.pack("<I", len(enc)) + enc


def _metadata_pda(mint: Pubkey) -> Pubkey:
    pda, _ = Pubkey.find_program_address(
        [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(mint)],
        METADATA_PROGRAM_ID,
    )
    return pda


def _edition_pda(mint: Pubkey) -> Pubkey:
    pda, _ = Pubkey.find_program_address(
        [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(mint), b"edition"],
        METADATA_PROGRAM_ID,
    )
    return pda


async def rpc(method: str, params: list) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            RPC_URL,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        )
        return resp.json()


async def update_and_verify(authority_kp: Keypair, mint_pubkey_str: str) -> str:
    mint_pk = Pubkey.from_string(mint_pubkey_str)
    collection_mint_pk = Pubkey.from_string(COLLECTION_MINT)
    authority_pk = authority_kp.pubkey()

    nft_metadata_pda = _metadata_pda(mint_pk)
    collection_metadata_pda = _metadata_pda(collection_mint_pk)
    collection_edition_pda = _edition_pda(collection_mint_pk)

    # 1. UnverifySizedCollectionItem — must unverify before updating collection field
    ix_unverify = Instruction(
        program_id=METADATA_PROGRAM_ID,
        accounts=[
            AccountMeta(pubkey=nft_metadata_pda, is_signer=False, is_writable=True),
            AccountMeta(pubkey=authority_pk, is_signer=True, is_writable=False),
            AccountMeta(pubkey=authority_pk, is_signer=True, is_writable=True),
            AccountMeta(pubkey=collection_mint_pk, is_signer=False, is_writable=False),
            AccountMeta(pubkey=collection_metadata_pda, is_signer=False, is_writable=True),
            AccountMeta(pubkey=collection_edition_pda, is_signer=False, is_writable=False),
        ],
        data=bytes([31]),  # UnverifySizedCollectionItem
    )

    # 2. UpdateMetadataAccountV2 — add creator + 5% royalties
    ix_update = Instruction(
        program_id=METADATA_PROGRAM_ID,
        accounts=[
            AccountMeta(pubkey=nft_metadata_pda, is_signer=False, is_writable=True),
            AccountMeta(pubkey=authority_pk, is_signer=True, is_writable=False),
        ],
        data=(
            bytes([15])                        # UpdateMetadataAccountV2 opcode
            + bytes([1])                       # data: Some(DataV2)
            + _borsh_str("Alpine Labs Builder Pass")
            + _borsh_str("ALBP")
            + _borsh_str(METADATA_URI)
            + struct.pack("<H", 500)           # seller_fee_basis_points = 5%
            + bytes([1])                       # creators: Some
            + struct.pack("<I", 1)             # 1 creator
            + bytes(authority_pk)              # creator pubkey (32 bytes)
            + bytes([1])                       # verified = true (authority signs this tx)
            + bytes([100])                     # share = 100%
            + bytes([1])                       # collection: Some
            + bytes([0])                       # verified = false (re-verified below)
            + bytes(collection_mint_pk)
            + bytes([0])                       # uses: None
            + bytes([0])                       # update_authority: None (keep existing)
            + bytes([0])                       # primary_sale_happened: None
            + bytes([0])                       # is_mutable: None
        ),
    )

    # 3. VerifySizedCollectionItem — re-verify collection
    ix_verify = Instruction(
        program_id=METADATA_PROGRAM_ID,
        accounts=[
            AccountMeta(pubkey=nft_metadata_pda, is_signer=False, is_writable=True),
            AccountMeta(pubkey=authority_pk, is_signer=True, is_writable=False),
            AccountMeta(pubkey=authority_pk, is_signer=True, is_writable=True),
            AccountMeta(pubkey=collection_mint_pk, is_signer=False, is_writable=False),
            AccountMeta(pubkey=collection_metadata_pda, is_signer=False, is_writable=True),
            AccountMeta(pubkey=collection_edition_pda, is_signer=False, is_writable=False),
        ],
        data=bytes([30]),  # VerifySizedCollectionItem
    )

    bh_resp = await rpc("getLatestBlockhash", [{"commitment": "confirmed"}])
    blockhash = Hash.from_string(bh_resp["result"]["value"]["blockhash"])

    msg = Message.new_with_blockhash([ix_unverify, ix_update, ix_verify], authority_pk, blockhash)
    tx = Transaction([authority_kp], msg, blockhash)
    tx_b64 = base64.b64encode(bytes(tx)).decode()

    send_resp = await rpc(
        "sendTransaction",
        [tx_b64, {"encoding": "base64", "skipPreflight": True, "maxRetries": 3}],
    )
    if "error" in send_resp:
        raise Exception(f"sendTransaction failed: {send_resp['error']}")
    sig = send_resp["result"]

    for _ in range(30):
        await asyncio.sleep(2)
        status_resp = await rpc(
            "getSignatureStatuses",
            [[sig], {"searchTransactionHistory": True}],
        )
        status = ((status_resp.get("result") or {}).get("value") or [None])[0]
        if status:
            if status.get("err"):
                raise Exception(f"Transaction failed on-chain: {status['err']}")
            if status.get("confirmationStatus") in ("confirmed", "finalized"):
                return sig

    raise Exception(f"Transaction not confirmed within 60s: {sig}")


async def main():
    authority_kp = Keypair.from_bytes(bytes(json.loads(AUTHORITY_KEYPAIR_JSON)))
    db = create_client(SUPABASE_URL, SUPABASE_KEY)

    rows = (
        db.table("builder_pass_mints")
        .select("mint_pubkey, user_id, status")
        .neq("mint_pubkey", "")
        .eq("status", "confirmed")
        .execute()
        .data
    )

    print(f"Found {len(rows)} confirmed Builder Pass mints to update")

    success = 0
    failed = 0

    for row in rows:
        mint_pubkey = row["mint_pubkey"]
        user_id = row["user_id"]
        print(f"  Updating mint={mint_pubkey} user={user_id} ... ", end="", flush=True)
        try:
            sig = await update_and_verify(authority_kp, mint_pubkey)
            print(f"OK ({sig})")
            success += 1
        except Exception as e:
            print(f"FAILED: {e}")
            failed += 1

        await asyncio.sleep(1)

    print(f"\nDone. success={success} failed={failed}")


if __name__ == "__main__":
    asyncio.run(main())
