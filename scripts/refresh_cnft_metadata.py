"""
Force Helius to re-index a cNFT by running updateMetadata on Bubblegum.

Step 1: approve_collection_authority on mpl-token-metadata
        Creates the CollectionAuthorityRecord PDA that Bubblegum requires.
        Skipped if the record already exists.

Step 2: updateMetadata on Bubblegum (is_mutable: Some(true), no content change)
        The explicit metadata-update instruction triggers Helius to re-fetch
        the json_uri and populate content.files / content.links in DAS.

Usage:
    cd seekerthon   (repo root)
    python scripts/refresh_cnft_metadata.py \\
        --asset-id <ASSET_ID> \\
        --tree <TREE_ADDRESS> \\
        --collection <COLLECTION_MINT> \\
        --leaf-owner <OWNER_WALLET> \\
        --creator <CREATOR_WALLET> \\
        --leaf-id <INT> \\
        --nonce <INT> \\
        --name "Builder Support: My Project" \\
        --symbol BSUP \\
        --uri https://app.seekerthon.com/api/v1/metadata/support/project/<UUID>

Requires backend/.env with SOLANA_MAINNET_RPC_URL and builder_pass_authority_keypair.
"""
import asyncio
import argparse
import base64
import hashlib
import json
import os
import struct
import sys

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

BUBBLEGUM    = Pubkey.from_string("BGUMAp9Gq7iTEuizy4pqaxsTyUCBK68MDfK752saRPUY")
TOKEN_META   = Pubkey.from_string("metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s")
SPL_NOOP     = Pubkey.from_string("noopb9bkMVfRPU8AsbpTUg8AQkHtKwMYZiFUjNRtMmV")
SPL_COMPRESS = Pubkey.from_string("cmtDvXumGCrqC1Age74AVPhSRVXJMd8PJS91L8KbNCK")
SYSTEM       = Pubkey.from_string("11111111111111111111111111111111")
SYSVAR_RENT  = Pubkey.from_string("SysvarRent111111111111111111111111111111111")


def _bs(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("<I", len(b)) + b


def _borsh_metadata_args(name: str, symbol: str, uri: str, creator: Pubkey, collection: Pubkey) -> bytes:
    d = _bs(name) + _bs(symbol) + _bs(uri)
    d += struct.pack("<H", 500)
    d += b"\x00"        # primary_sale_happened = false
    d += b"\x01"        # is_mutable = true
    d += b"\x00"        # edition_nonce: None
    d += b"\x01\x00"   # token_standard: Some(NonFungible=0)
    d += b"\x01" + b"\x01" + bytes(collection)  # collection: Some({verified=true, key})
    d += b"\x00"        # uses: None
    d += b"\x00"        # token_program_version: Original
    d += struct.pack("<I", 1) + bytes(creator) + b"\x01\x64"  # 1 creator, verified, share=100
    return d


def _borsh_update_args() -> bytes:
    return (
        b"\x00"       # name: None
        + b"\x00"     # symbol: None
        + b"\x00"     # uri: None
        + b"\x00"     # creators: None
        + b"\x00"     # seller_fee_basis_points: None
        + b"\x00"     # primary_sale_happened: None
        + b"\x01\x01" # is_mutable: Some(true) — minimal touch to trigger re-index
    )


async def _rpc(method: str, params, rpc_url: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        return r.json()


async def _send_and_confirm(tx_b64: str, rpc_url: str) -> str:
    resp = await _rpc("sendTransaction", [tx_b64, {"encoding": "base64", "preflightCommitment": "confirmed"}], rpc_url)
    if "error" in resp:
        raise Exception(f"sendTransaction failed: {resp['error']}")
    sig = resp["result"]
    for _ in range(30):
        await asyncio.sleep(2)
        conf = await _rpc("getSignatureStatuses", [[sig], {"searchTransactionHistory": True}], rpc_url)
        s = ((conf.get("result") or {}).get("value") or [None])[0]
        if s:
            if s.get("err"):
                raise Exception(f"on-chain error: {s['err']}")
            if s.get("confirmationStatus") in ("confirmed", "finalized"):
                return sig
    raise Exception("not confirmed within 60s")


async def _send_ix(ix: Instruction, authority: Keypair, rpc_url: str) -> str:
    bh        = await _rpc("getLatestBlockhash", [{"commitment": "confirmed"}], rpc_url)
    blockhash = Hash.from_string(bh["result"]["value"]["blockhash"])
    msg       = Message.new_with_blockhash([ix], authority.pubkey(), blockhash)
    tx        = Transaction([authority], msg, blockhash)
    return await _send_and_confirm(base64.b64encode(bytes(tx)).decode(), rpc_url)


async def main(args):
    rpc_url   = os.environ["SOLANA_MAINNET_RPC_URL"]
    authority = Keypair.from_bytes(bytes(json.loads(os.environ["builder_pass_authority_keypair"])))

    tree_pk  = Pubkey.from_string(args.tree)
    coll_pk  = Pubkey.from_string(args.collection)
    owner_pk = Pubkey.from_string(args.leaf_owner)
    creator_pk = Pubkey.from_string(args.creator)

    tree_config, _ = Pubkey.find_program_address([bytes(tree_pk)], BUBBLEGUM)
    coll_meta, _   = Pubkey.find_program_address(
        [b"metadata", bytes(TOKEN_META), bytes(coll_pk)], TOKEN_META
    )
    coll_auth_record, _ = Pubkey.find_program_address(
        [b"metadata", bytes(TOKEN_META), bytes(coll_pk), b"collection_authority", bytes(authority.pubkey())],
        TOKEN_META,
    )

    print(f"Authority          : {authority.pubkey()}")
    print(f"coll_auth_record   : {coll_auth_record}")

    # ── Step 1: approve_collection_authority (mpl-token-metadata) ────────────
    existing = await _rpc("getAccountInfo", [str(coll_auth_record), {"encoding": "base64"}], rpc_url)
    if existing["result"]["value"]:
        print("CollectionAuthorityRecord already exists, skipping step 1.")
    else:
        print("\nStep 1: Creating CollectionAuthorityRecord...")
        approve_ix = Instruction(
            program_id=TOKEN_META,
            accounts=[
                AccountMeta(pubkey=coll_auth_record,    is_signer=False, is_writable=True),
                AccountMeta(pubkey=authority.pubkey(),  is_signer=False, is_writable=False),
                AccountMeta(pubkey=authority.pubkey(),  is_signer=True,  is_writable=True),
                AccountMeta(pubkey=authority.pubkey(),  is_signer=True,  is_writable=True),
                AccountMeta(pubkey=coll_meta,           is_signer=False, is_writable=False),
                AccountMeta(pubkey=coll_pk,             is_signer=False, is_writable=False),
                AccountMeta(pubkey=SYSTEM,              is_signer=False, is_writable=False),
                AccountMeta(pubkey=SYSVAR_RENT,         is_signer=False, is_writable=False),
            ],
            data=bytes([23]),
        )
        sig1 = await _send_ix(approve_ix, authority, rpc_url)
        print(f"CollectionAuthorityRecord created  sig={sig1}")

    # ── Step 2: updateMetadata (Bubblegum) ───────────────────────────────────
    print("\nStep 2: Fetching asset proof for updateMetadata...")
    pr = await _rpc("getAssetProof", {"id": args.asset_id}, rpc_url)
    if "error" in pr:
        raise Exception(f"getAssetProof failed: {pr['error']}")
    root_b      = bytes(Pubkey.from_string(pr["result"]["root"]))
    proof_nodes = pr["result"]["proof"]
    print(f"Root: {pr['result']['root']}  depth: {len(proof_nodes)}")

    disc    = hashlib.sha256(b"global:update_metadata").digest()[:8]
    ix_data = (
        disc
        + root_b
        + struct.pack("<Q", args.nonce)
        + struct.pack("<I", args.leaf_id)
        + _borsh_metadata_args(args.name, args.symbol, args.uri, creator_pk, coll_pk)
        + _borsh_update_args()
    )

    proof_metas = [
        AccountMeta(pubkey=Pubkey.from_string(n), is_signer=False, is_writable=False)
        for n in proof_nodes
    ]
    accounts = [
        AccountMeta(pubkey=tree_config,         is_signer=False, is_writable=False),
        AccountMeta(pubkey=authority.pubkey(),  is_signer=True,  is_writable=False),
        AccountMeta(pubkey=coll_pk,             is_signer=False, is_writable=False),
        AccountMeta(pubkey=coll_meta,           is_signer=False, is_writable=True),
        AccountMeta(pubkey=coll_auth_record,    is_signer=False, is_writable=False),
        AccountMeta(pubkey=owner_pk,            is_signer=False, is_writable=False),
        AccountMeta(pubkey=owner_pk,            is_signer=False, is_writable=False),
        AccountMeta(pubkey=authority.pubkey(),  is_signer=True,  is_writable=True),
        AccountMeta(pubkey=tree_pk,             is_signer=False, is_writable=True),
        AccountMeta(pubkey=SPL_NOOP,            is_signer=False, is_writable=False),
        AccountMeta(pubkey=SPL_COMPRESS,        is_signer=False, is_writable=False),
        AccountMeta(pubkey=TOKEN_META,          is_signer=False, is_writable=False),
        AccountMeta(pubkey=SYSTEM,              is_signer=False, is_writable=False),
    ] + proof_metas

    update_ix = Instruction(program_id=BUBBLEGUM, accounts=accounts, data=bytes(ix_data))
    print("Sending updateMetadata...")
    sig2 = await _send_ix(update_ix, authority, rpc_url)
    print(f"updateMetadata OK  sig={sig2}")

    print("\nDone. Helius should re-fetch the metadata URI within a few minutes.")
    print("Check getAsset in ~5 min to confirm content.files is populated.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Force Helius to re-index a cNFT by sending a minimal updateMetadata instruction")
    parser.add_argument("--asset-id",   required=True, help="cNFT asset ID")
    parser.add_argument("--tree",       required=True, help="Merkle tree address")
    parser.add_argument("--collection", required=True, help="Collection mint address")
    parser.add_argument("--leaf-owner", required=True, help="Current leaf owner wallet")
    parser.add_argument("--creator",    required=True, help="Creator wallet address")
    parser.add_argument("--leaf-id",    required=True, type=int, help="Leaf index in the tree")
    parser.add_argument("--nonce",      required=True, type=int, help="Leaf nonce")
    parser.add_argument("--name",       required=True, help="NFT name (e.g. 'Builder Support: My Project')")
    parser.add_argument("--symbol",     default="BSUP", help="NFT symbol (default: BSUP)")
    parser.add_argument("--uri",        required=True, help="Metadata JSON URI")
    args = parser.parse_args()
    asyncio.run(main(args))
