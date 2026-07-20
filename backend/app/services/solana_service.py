"""
Solana service: reads on-chain state and builds unsigned vote transactions.
Uses solders for low-level Solana types and anchorpy for program interaction.
"""
import asyncio
import base64
import hashlib
import json
import logging
import math
import struct
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Tuple

from solders.keypair import Keypair as SoldersKeypair
from solders.pubkey import Pubkey
from solders.signature import Signature as SoldersSignature
from solders.transaction import Transaction
from solders.message import Message
from solders.instruction import Instruction, AccountMeta
from solders.hash import Hash
import httpx
from base58 import b58decode
from cryptography.fernet import Fernet

from app.config import get_settings
from app.db import get_supabase_admin

_log = logging.getLogger(__name__)
_settings = get_settings()

RPC_URL = _settings.solana_rpc_url
MAINNET_RPC_URL = _settings.solana_mainnet_rpc_url
SKR_MINT = _settings.skr_token_mint
GENESIS_COLLECTION = _settings.seeker_genesis_collection
ESCROW_PROGRAM = _settings.escrow_program_id
USDC_MINT = _settings.usdc_mint               # mainnet — Builder Pass flow
ESCROW_USDC_MINT = _settings.escrow_usdc_mint  # devnet or mainnet — escrow flow
USDC_DECIMALS = 6
MAX_MULTIPLIER = _settings.max_vote_multiplier
SKR_PER_STEP = _settings.skr_per_multiplier_step

# SKR staking program — on-chain contract where SKR holders stake
SKR_STAKING_PROGRAM = "SKRskrmtL83pcL4YqLWt6iPefDqwXQWHSw9S9vz94BZ"
_STAKING_ACCT_SIZE = 169    # per-user staking account size in bytes
_STAKING_WALLET_OFFSET = 41 # user wallet pubkey starts at byte 41
_STAKING_AMOUNT_OFFSET = 105 # staked u64 (LE, 6 decimals) starts at byte 105

# SPL Token program
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
TOKEN_2022_PROGRAM_ID = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
METADATA_PROGRAM_ID = Pubkey.from_string("metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s")
ASSOCIATED_TOKEN_PROGRAM = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")
ED25519_PROGRAM_ID = Pubkey.from_string("Ed25519SigVerify111111111111111111111111111")
INSTRUCTIONS_SYSVAR_ID = Pubkey.from_string("Sysvar1nstructions1111111111111111111111111")
CLAIM_MESSAGE_PREFIX = b"seekerthon-claim:v1"
BUILDER_PASS_PENDING_TTL = timedelta(minutes=10)


def _escrow_platform_admin_keypair() -> SoldersKeypair:
    raw = json.loads(_settings.escrow_platform_admin_keypair)
    if not raw:
        raise ValueError("ESCROW_PLATFORM_ADMIN_KEYPAIR is required for escrow winner-claim flow")
    return SoldersKeypair.from_bytes(bytes(raw))


def _builder_pass_pending_cipher() -> Fernet:
    key = hashlib.sha256(_settings.jwt_secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _encrypt_builder_pass_mint_keypair(mint_kp: SoldersKeypair) -> str:
    return _builder_pass_pending_cipher().encrypt(bytes(mint_kp)).decode("utf-8")


def _decrypt_builder_pass_mint_keypair(ciphertext: str) -> SoldersKeypair:
    raw = _builder_pass_pending_cipher().decrypt(ciphertext.encode("utf-8"))
    return SoldersKeypair.from_bytes(raw)


def builder_pass_authority_pubkey() -> str:
    raw = json.loads(_settings.builder_pass_authority_keypair)
    if not raw:
        raise ValueError("BUILDER_PASS_AUTHORITY_KEYPAIR is required for Builder Pass minting")
    return str(SoldersKeypair.from_bytes(bytes(raw)).pubkey())


async def get_builder_pass_mint_availability() -> dict[str, Any]:
    authority_pubkey = builder_pass_authority_pubkey()
    min_required = _settings.builder_pass_min_mint_balance_lamports
    resp = await _rpc_post(
        "getBalance",
        [authority_pubkey, {"commitment": "confirmed"}],
        rpc_url=MAINNET_RPC_URL,
    )
    balance = int(resp["result"]["value"])
    available = balance >= min_required
    return {
        "available": available,
        "authority_balance_lamports": balance,
        "min_required_lamports": min_required,
        "message": "" if available else "Builder Pass minting is temporarily unavailable.",
    }


async def fetch_sol_usd_price() -> dict[str, Any]:
    """Fetch the current SOL/USD quote from CoinGecko's public simple price endpoint."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            _settings.sol_usd_price_url,
            params={"ids": "solana", "vs_currencies": "usd"},
        )
    resp.raise_for_status()
    data = resp.json()
    price = (data.get("solana") or {}).get("usd")
    if price is None:
        raise ValueError("SOL/USD price missing from price response")
    return {
        "price_usd": float(price),
        "source": "coingecko",
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def _anchor_discriminator(name: str) -> bytes:
    import hashlib
    return hashlib.sha256(f"global:{name}".encode()).digest()[:8]


def _claim_message(
    escrow_program: Pubkey,
    escrow: Pubkey,
    hackathon_id_bytes: bytes,
    project_id_bytes: bytes,
    winner: Pubkey,
    prize_usdc: int,
    expires_at_ts: int,
    nonce: bytes,
) -> bytes:
    return (
        CLAIM_MESSAGE_PREFIX
        + bytes(escrow_program)
        + bytes(escrow)
        + hackathon_id_bytes
        + project_id_bytes
        + bytes(winner)
        + struct.pack("<Q", prize_usdc)
        + struct.pack("<q", expires_at_ts)
        + nonce
    )


def _ed25519_verify_instruction(pubkey: Pubkey, signature: bytes, message: bytes) -> Instruction:
    sig_offset = 16
    pk_offset = sig_offset + 64
    msg_offset = pk_offset + 32
    data = (
        bytes([1, 0])
        + struct.pack("<H", sig_offset)
        + struct.pack("<H", 0xFFFF)
        + struct.pack("<H", pk_offset)
        + struct.pack("<H", 0xFFFF)
        + struct.pack("<H", msg_offset)
        + struct.pack("<H", len(message))
        + struct.pack("<H", 0xFFFF)
        + signature
        + bytes(pubkey)
        + message
    )
    return Instruction(program_id=ED25519_PROGRAM_ID, accounts=[], data=data)


def _tx_message(tx_data: dict[str, Any]) -> dict[str, Any]:
    return tx_data.get("transaction", {}).get("message", {}) or {}


def _tx_signers(tx_data: dict[str, Any]) -> set[str]:
    return {
        acc.get("pubkey", "")
        for acc in _tx_message(tx_data).get("accountKeys", [])
        if isinstance(acc, dict) and acc.get("signer")
    }


def _tx_account_keys(tx_data: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for acc in _tx_message(tx_data).get("accountKeys", []):
        keys.add(acc.get("pubkey", "") if isinstance(acc, dict) else str(acc))
    return keys


def _instruction_data(ix: dict[str, Any]) -> bytes:
    data = ix.get("data")
    if isinstance(data, str):
        try:
            return b58decode(data)
        except Exception:
            return b""
    if isinstance(data, list) and data and isinstance(data[0], str):
        enc = data[1] if len(data) > 1 else "base64"
        try:
            return base64.b64decode(data[0]) if enc == "base64" else b58decode(data[0])
        except Exception:
            return b""
    return b""


def _outer_instructions(tx_data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        ix for ix in (_tx_message(tx_data).get("instructions") or [])
        if isinstance(ix, dict)
    ]


def _has_program_instruction(
    tx_data: dict[str, Any],
    program_id: str,
    discriminator: bytes | None = None,
    required_accounts: list[str] | None = None,
) -> bool:
    required = set(required_accounts or [])
    for ix in _outer_instructions(tx_data):
        if ix.get("programId") != program_id:
            continue
        if discriminator is not None and not _instruction_data(ix).startswith(discriminator):
            continue
        accounts = set(ix.get("accounts") or [])
        if required and not required.issubset(accounts):
            continue
        return True
    return False


async def _rpc_post(method: str, params: list, rpc_url: str = RPC_URL) -> dict:
    for attempt in range(3):
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        if resp.status_code != 429:
            resp.raise_for_status()
            return resp.json()
        if attempt < 2:
            await asyncio.sleep(2 ** attempt)
    resp.raise_for_status()
    return resp.json()


def _find_ata(wallet: Pubkey, mint: Pubkey) -> Pubkey:
    """Derive associated token account address."""
    pda, _ = Pubkey.find_program_address(
        [bytes(wallet), bytes(TOKEN_PROGRAM_ID), bytes(mint)],
        ASSOCIATED_TOKEN_PROGRAM,
    )
    return pda


async def get_skr_balance(wallet_address: str) -> Tuple[int, int]:
    """
    Returns (skr_balance, skr_staked) as whole-token integers (6 decimals stripped).
    skr_balance: liquid SKR in all token accounts owned by the wallet
    skr_staked: SKR locked in the SKR staking program (per-user account at offset 105)
    """
    # --- Liquid balance: all token accounts for this wallet/mint ---
    balance_raw = 0
    decimals = 6
    try:
        resp = await _rpc_post(
            "getTokenAccountsByOwner",
            [wallet_address, {"mint": SKR_MINT}, {"encoding": "jsonParsed", "commitment": "confirmed"}],
            rpc_url=MAINNET_RPC_URL,
        )
        for acct in (resp.get("result", {}).get("value") or []):
            info = acct.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
            ta = info.get("tokenAmount", {})
            balance_raw += int(ta.get("amount", 0))
            decimals = int(ta.get("decimals", decimals))
    except Exception as exc:
        _log.warning("SKR liquid balance lookup failed for %s: %s", wallet_address, exc)

    divisor = 10 ** decimals

    # --- Staked balance: getProgramAccounts on SKR staking program filtered by wallet ---
    # Per-user staking accounts are 169 bytes; wallet pubkey lives at byte offset 41;
    # staked u64 (LE) lives at byte offset 105.
    staked_raw = 0
    try:
        stake_resp = await _rpc_post(
            "getProgramAccounts",
            [
                SKR_STAKING_PROGRAM,
                {
                    "encoding": "base64",
                    "commitment": "confirmed",
                    "filters": [
                        {"dataSize": _STAKING_ACCT_SIZE},
                        {"memcmp": {"offset": _STAKING_WALLET_OFFSET, "bytes": wallet_address}},
                    ],
                },
            ],
            rpc_url=MAINNET_RPC_URL,
        )
        accounts = stake_resp.get("result") or []
        if accounts:
            data = base64.b64decode(accounts[0]["account"]["data"][0])
            if len(data) >= _STAKING_AMOUNT_OFFSET + 8:
                staked_raw = struct.unpack_from("<Q", data, _STAKING_AMOUNT_OFFSET)[0]
                _log.info("Staked SKR for %s: %d raw (%s whole)", wallet_address, staked_raw, staked_raw // divisor)
    except Exception as exc:
        _log.warning("Staked SKR lookup failed for %s: %s", wallet_address, exc)

    return balance_raw // divisor, staked_raw // divisor


def compute_vote_weight(skr_staked: int, has_builder_pass: bool = False) -> float:
    """
    Weight formula: 1 + log2(1 + staked / SKR_PER_STEP), capped at MAX_MULTIPLIER.
    Builder Pass multiplies the result by 5x (capped at MAX_MULTIPLIER * 5).
    Only on-chain *staked* SKR counts — liquid balance does not contribute, so
    influence requires lock-up rather than just holding tokens.
    """
    raw = 1.0 + math.log2(1.0 + skr_staked / SKR_PER_STEP)
    base = round(min(raw, MAX_MULTIPLIER), 4)
    if has_builder_pass:
        return round(min(base * 5.0, MAX_MULTIPLIER * 5.0), 4)
    return base


def _borsh_str(s: str) -> bytes:
    enc = s.encode("utf-8")
    return struct.pack("<I", len(enc)) + enc


async def verify_nft_collection(mint_pk_str: str) -> None:
    """
    Call VerifyCollection on a freshly-minted NFT so wallets don't flag it as spam.
    Signed entirely server-side by authority_kp (the collection's update authority).
    Non-fatal: logs a warning on failure rather than raising.
    """
    settings = _settings
    if not settings.builder_pass_collection_mint:
        return

    authority_kp = SoldersKeypair.from_bytes(bytes(json.loads(settings.builder_pass_authority_keypair)))
    authority_pk = authority_kp.pubkey()

    mint_pk = Pubkey.from_string(mint_pk_str)
    collection_mint_pk = Pubkey.from_string(settings.builder_pass_collection_mint)

    metadata_pda, _ = Pubkey.find_program_address(
        [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(mint_pk)],
        METADATA_PROGRAM_ID,
    )
    collection_metadata_pda, _ = Pubkey.find_program_address(
        [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(collection_mint_pk)],
        METADATA_PROGRAM_ID,
    )
    collection_edition_pda, _ = Pubkey.find_program_address(
        [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(collection_mint_pk), b"edition"],
        METADATA_PROGRAM_ID,
    )

    ix_verify = Instruction(
        program_id=METADATA_PROGRAM_ID,
        accounts=[
            AccountMeta(pubkey=metadata_pda, is_signer=False, is_writable=True),
            AccountMeta(pubkey=authority_pk, is_signer=True, is_writable=False),   # collection authority
            AccountMeta(pubkey=authority_pk, is_signer=True, is_writable=True),    # payer
            AccountMeta(pubkey=collection_mint_pk, is_signer=False, is_writable=False),
            AccountMeta(pubkey=collection_metadata_pda, is_signer=False, is_writable=True),
            AccountMeta(pubkey=collection_edition_pda, is_signer=False, is_writable=False),
        ],
        data=bytes([30]),  # VerifySizedCollectionItem (sized collections require 30, not 18)
    )

    try:
        bh_resp = await _rpc_post("getLatestBlockhash", [{"commitment": "confirmed"}], rpc_url=MAINNET_RPC_URL)
        recent_blockhash = Hash.from_string(bh_resp["result"]["value"]["blockhash"])
        msg = Message.new_with_blockhash([ix_verify], authority_pk, recent_blockhash)
        tx = Transaction([authority_kp], msg, recent_blockhash)
        tx_b64 = base64.b64encode(bytes(tx)).decode()

        send = await _rpc_post(
            "sendTransaction",
            [tx_b64, {"encoding": "base64", "skipPreflight": True, "maxRetries": 3}],
            rpc_url=MAINNET_RPC_URL,
        )
        if "error" in send:
            _log.warning("VerifyCollection send failed for mint=%s: %s", mint_pk_str, send["error"])
            return

        sig = send["result"]
        _log.info("VerifyCollection submitted: %s", sig)

        for _ in range(15):
            await asyncio.sleep(2)
            conf = await _rpc_post(
                "getSignatureStatuses",
                [[sig], {"searchTransactionHistory": True}],
                rpc_url=MAINNET_RPC_URL,
            )
            status = ((conf.get("result") or {}).get("value") or [None])[0]
            if status:
                if status.get("err"):
                    _log.warning("VerifyCollection tx failed on-chain for mint=%s: %s", mint_pk_str, status["err"])
                    return
                if status.get("confirmationStatus") in ("confirmed", "finalized"):
                    _log.info("VerifyCollection confirmed for mint=%s", mint_pk_str)
                    return
    except Exception as exc:
        _log.warning("VerifyCollection exception for mint=%s: %s", mint_pk_str, exc)


async def build_unsigned_combined_mint_transaction(
    buyer_wallet: str,
    usdc_amount: int,
) -> tuple[str, str, int, str, int, str]:
    """
    Build an unsigned combined payment + NFT-mint transaction.
    The buyer signs a clean unsigned transaction; the backend stores encrypted
    mint signer material and completes signatures after /claim.

    All 9 instructions are atomic — either payment AND NFT mint both land, or neither does.
    Returns (unsigned_tx_b64, mint_pubkey, amount_raw, amount_display, sol_fee_lamports, sol_fee_display).
    """
    settings = _settings
    db = get_supabase_admin()
    now = datetime.now(timezone.utc)
    db.table("builder_pass_pending_mints").delete().lt("expires_at", now.isoformat()).execute()

    authority_kp = SoldersKeypair.from_bytes(bytes(json.loads(settings.builder_pass_authority_keypair)))
    authority_pk = authority_kp.pubkey()

    mint_kp = SoldersKeypair()
    mint_pk = mint_kp.pubkey()

    buyer_pk = Pubkey.from_string(buyer_wallet)
    usdc_mint_pk = Pubkey.from_string(USDC_MINT)
    treasury_pk = Pubkey.from_string(settings.builder_pass_treasury)
    collection_mint_pk = Pubkey.from_string(settings.builder_pass_collection_mint)

    buyer_usdc_ata = _find_ata(buyer_pk, usdc_mint_pk)
    treasury_usdc_ata = _find_ata(treasury_pk, usdc_mint_pk)
    buyer_nft_ata = _find_ata(buyer_pk, mint_pk)

    metadata_pda, _ = Pubkey.find_program_address(
        [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(mint_pk)],
        METADATA_PROGRAM_ID,
    )
    edition_pda, _ = Pubkey.find_program_address(
        [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(mint_pk), b"edition"],
        METADATA_PROGRAM_ID,
    )

    SYSVAR_RENT = Pubkey.from_string("SysvarRent111111111111111111111111111111111")
    rent_resp = await _rpc_post("getMinimumBalanceForRentExemption", [82], rpc_url=MAINNET_RPC_URL)
    mint_rent = rent_resp["result"]

    # ── Payment instructions (buyer signs) ──────────────────────────────────

    # 1. Idempotent create treasury USDC ATA (no-op if already exists)
    ix_create_treasury_ata = Instruction(
        program_id=ASSOCIATED_TOKEN_PROGRAM,
        accounts=[
            AccountMeta(pubkey=buyer_pk, is_signer=True, is_writable=True),
            AccountMeta(pubkey=treasury_usdc_ata, is_signer=False, is_writable=True),
            AccountMeta(pubkey=treasury_pk, is_signer=False, is_writable=False),
            AccountMeta(pubkey=usdc_mint_pk, is_signer=False, is_writable=False),
            AccountMeta(pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        ],
        data=bytes([1]),
    )

    # 2. USDC transfer: buyer → treasury
    ix_usdc_transfer = Instruction(
        program_id=TOKEN_PROGRAM_ID,
        accounts=[
            AccountMeta(pubkey=buyer_usdc_ata, is_signer=False, is_writable=True),
            AccountMeta(pubkey=treasury_usdc_ata, is_signer=False, is_writable=True),
            AccountMeta(pubkey=buyer_pk, is_signer=True, is_writable=False),
        ],
        data=bytes([3]) + struct.pack("<Q", usdc_amount),
    )

    # NFT mint instructions (buyer pays, authority_kp + mint_kp sign)

    # 3. CreateAccount - buyer pays rent for the new mint account
    ix_create_account = Instruction(
        program_id=SYSTEM_PROGRAM_ID,
        accounts=[
            AccountMeta(pubkey=buyer_pk, is_signer=True, is_writable=True),
            AccountMeta(pubkey=mint_pk, is_signer=True, is_writable=True),
        ],
        data=(
            struct.pack("<I", 0)
            + struct.pack("<Q", mint_rent)
            + struct.pack("<Q", 82)
            + bytes(TOKEN_PROGRAM_ID)
        ),
    )

    # 4. InitializeMint - 0 decimals, freeze_authority set for Metaplex Master Edition
    # SPL Token COption<Pubkey>: 1-byte discriminant (0=None, 1=Some) + 32-byte pubkey
    ix_init_mint = Instruction(
        program_id=TOKEN_PROGRAM_ID,
        accounts=[
            AccountMeta(pubkey=mint_pk, is_signer=False, is_writable=True),
            AccountMeta(pubkey=SYSVAR_RENT, is_signer=False, is_writable=False),
        ],
        data=(
            bytes([0])
            + bytes([0])
            + bytes(authority_pk)
            + bytes([1])
            + bytes(authority_pk)
        ),
    )

    # 5. Create buyer's NFT ATA (buyer pays)
    ix_create_nft_ata = Instruction(
        program_id=ASSOCIATED_TOKEN_PROGRAM,
        accounts=[
            AccountMeta(pubkey=buyer_pk, is_signer=True, is_writable=True),
            AccountMeta(pubkey=buyer_nft_ata, is_signer=False, is_writable=True),
            AccountMeta(pubkey=buyer_pk, is_signer=False, is_writable=False),
            AccountMeta(pubkey=mint_pk, is_signer=False, is_writable=False),
            AccountMeta(pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        ],
        data=bytes([1]),
    )

    # 6. MintTo - 1 token to buyer's ATA
    ix_mint_to = Instruction(
        program_id=TOKEN_PROGRAM_ID,
        accounts=[
            AccountMeta(pubkey=mint_pk, is_signer=False, is_writable=True),
            AccountMeta(pubkey=buyer_nft_ata, is_signer=False, is_writable=True),
            AccountMeta(pubkey=authority_pk, is_signer=True, is_writable=False),
        ],
        data=bytes([7]) + struct.pack("<Q", 1),
    )

    # 7. CreateMetadataAccountV3
    ix_create_metadata = Instruction(
        program_id=METADATA_PROGRAM_ID,
        accounts=[
            AccountMeta(pubkey=metadata_pda, is_signer=False, is_writable=True),
            AccountMeta(pubkey=mint_pk, is_signer=False, is_writable=False),
            AccountMeta(pubkey=authority_pk, is_signer=True, is_writable=False),  # mint authority
            AccountMeta(pubkey=buyer_pk, is_signer=True, is_writable=True),       # payer
            AccountMeta(pubkey=authority_pk, is_signer=False, is_writable=False), # update authority
            AccountMeta(pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=SYSVAR_RENT, is_signer=False, is_writable=False),
        ],
        data=(
            bytes([33])
            + _borsh_str("Alpine Labs Builder Pass")
            + _borsh_str("ALBP")
            + _borsh_str(settings.builder_pass_metadata_uri)
            + struct.pack("<H", 500)            # seller_fee_basis_points = 5%
            + bytes([1])                       # creators: Some
            + struct.pack("<I", 1)             # 1 creator
            + bytes(authority_pk)              # creator pubkey
            + bytes([1])                       # verified = true (authority signs this tx)
            + bytes([100])                     # share = 100%
            + bytes([1])                       # collection: Some
            + bytes([0])                       # verified = false
            + bytes(collection_mint_pk)
            + bytes([0])                       # uses: None
            + bytes([1])                       # is_mutable = true
            + bytes([0])                       # collection_details: None
        ),
    )

    # 8. CreateMasterEditionV3 - max_supply = Some(0)
    ix_create_edition = Instruction(
        program_id=METADATA_PROGRAM_ID,
        accounts=[
            AccountMeta(pubkey=edition_pda, is_signer=False, is_writable=True),
            AccountMeta(pubkey=mint_pk, is_signer=False, is_writable=True),
            AccountMeta(pubkey=authority_pk, is_signer=True, is_writable=False),  # update authority
            AccountMeta(pubkey=authority_pk, is_signer=True, is_writable=False),  # mint authority
            AccountMeta(pubkey=buyer_pk, is_signer=True, is_writable=True),       # payer
            AccountMeta(pubkey=metadata_pda, is_signer=False, is_writable=True),
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=SYSVAR_RENT, is_signer=False, is_writable=False),
        ],
        data=bytes([17]) + bytes([1]) + struct.pack("<Q", 0),
    )

    collection_metadata_pda, _ = Pubkey.find_program_address(
        [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(collection_mint_pk)],
        METADATA_PROGRAM_ID,
    )
    collection_edition_pda, _ = Pubkey.find_program_address(
        [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(collection_mint_pk), b"edition"],
        METADATA_PROGRAM_ID,
    )

    ix_verify_collection = Instruction(
        program_id=METADATA_PROGRAM_ID,
        accounts=[
            AccountMeta(pubkey=metadata_pda, is_signer=False, is_writable=True),
            AccountMeta(pubkey=authority_pk, is_signer=True, is_writable=False),
            AccountMeta(pubkey=buyer_pk, is_signer=True, is_writable=True),
            AccountMeta(pubkey=collection_mint_pk, is_signer=False, is_writable=False),
            AccountMeta(pubkey=collection_metadata_pda, is_signer=False, is_writable=True),
            AccountMeta(pubkey=collection_edition_pda, is_signer=False, is_writable=False),
        ],
        data=bytes([30]),  # VerifySizedCollectionItem — sized collections require 30 not 18
    )

    bh_resp = await _rpc_post("getLatestBlockhash", [{"commitment": "confirmed"}], rpc_url=MAINNET_RPC_URL)
    recent_blockhash = Hash.from_string(bh_resp["result"]["value"]["blockhash"])

    instructions = [
        ix_create_treasury_ata, ix_usdc_transfer,
        ix_create_account, ix_init_mint, ix_create_nft_ata,
        ix_mint_to, ix_create_metadata, ix_create_edition, ix_verify_collection,
    ]

    # Buyer is fee payer and pays all rent/ATA/metadata/verification SOL costs directly.
    msg = Message.new_with_blockhash(instructions, buyer_pk, recent_blockhash)

    # Keep the transaction completely unsigned so wallets simulate it without
    # partially-signed transaction warnings. The backend keeps only the two
    # non-buyer signing keys needed to finish this exact message after the buyer signs.
    tx = Transaction.new_unsigned(msg)
    tx_b64 = base64.b64encode(bytes(tx)).decode()

    # Pre-flight: simulate with sigVerify=False (buyer hasn't signed yet)
    sim = await _rpc_post(
        "simulateTransaction",
        [tx_b64, {"encoding": "base64", "commitment": "confirmed", "sigVerify": False}],
        rpc_url=MAINNET_RPC_URL,
    )
    sim_val = sim.get("result", {}).get("value", {})
    if sim_val.get("err"):
        logs = sim_val.get("logs") or []
        raise ValueError(f"Combined mint simulation failed: {sim_val['err']} — {logs}")

    db.table("builder_pass_pending_mints").delete().eq("buyer_wallet", buyer_wallet).execute()
    db.table("builder_pass_pending_mints").insert(
        {
            "mint_pubkey": str(mint_pk),
            "buyer_wallet": buyer_wallet,
            "message_b64": base64.b64encode(bytes(tx.message)).decode(),
            "recent_blockhash": str(recent_blockhash),
            "encrypted_mint_keypair": _encrypt_builder_pass_mint_keypair(mint_kp),
            "expires_at": (now + BUILDER_PASS_PENDING_TTL).isoformat(),
        }
    ).execute()

    _log.info("Unsigned combined mint tx built and simulated OK for buyer=%s mint=%s", buyer_wallet, mint_pk)
    return (
        tx_b64,
        str(mint_pk),
        usdc_amount,
        f"{usdc_amount / 1_000_000:.6g}",
        0,
        "0",
    )


async def mint_nft_server_side(buyer_wallet: str) -> tuple[str, str]:
    """
    Mint a Builder Pass NFT to buyer_wallet, fully paid and signed by the authority keypair.
    The buyer receives the NFT but does not sign this transaction.
    Returns (mint_pubkey_str, confirmed_tx_signature).
    """
    settings = _settings
    authority_kp = SoldersKeypair.from_bytes(bytes(json.loads(settings.builder_pass_authority_keypair)))
    authority_pk = authority_kp.pubkey()

    mint_kp = SoldersKeypair()
    mint_pk = mint_kp.pubkey()

    buyer_pk = Pubkey.from_string(buyer_wallet)
    collection_mint_pk = Pubkey.from_string(settings.builder_pass_collection_mint)

    buyer_nft_ata = _find_ata(buyer_pk, mint_pk)
    metadata_pda, _ = Pubkey.find_program_address(
        [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(mint_pk)],
        METADATA_PROGRAM_ID,
    )
    edition_pda, _ = Pubkey.find_program_address(
        [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(mint_pk), b"edition"],
        METADATA_PROGRAM_ID,
    )
    collection_metadata_pda, _ = Pubkey.find_program_address(
        [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(collection_mint_pk)],
        METADATA_PROGRAM_ID,
    )
    collection_edition_pda, _ = Pubkey.find_program_address(
        [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(collection_mint_pk), b"edition"],
        METADATA_PROGRAM_ID,
    )

    SYSVAR_RENT = Pubkey.from_string("SysvarRent111111111111111111111111111111111")
    rent_resp = await _rpc_post("getMinimumBalanceForRentExemption", [82], rpc_url=MAINNET_RPC_URL)
    mint_rent = rent_resp["result"]

    # 1. CreateAccount — authority pays rent for new mint account
    ix_create_account = Instruction(
        program_id=SYSTEM_PROGRAM_ID,
        accounts=[
            AccountMeta(pubkey=authority_pk, is_signer=True, is_writable=True),
            AccountMeta(pubkey=mint_pk, is_signer=True, is_writable=True),
        ],
        data=(
            struct.pack("<I", 0)
            + struct.pack("<Q", mint_rent)
            + struct.pack("<Q", 82)
            + bytes(TOKEN_PROGRAM_ID)
        ),
    )

    # 2. InitializeMint — 0 decimals, authority controls mint + freeze
    ix_init_mint = Instruction(
        program_id=TOKEN_PROGRAM_ID,
        accounts=[
            AccountMeta(pubkey=mint_pk, is_signer=False, is_writable=True),
            AccountMeta(pubkey=SYSVAR_RENT, is_signer=False, is_writable=False),
        ],
        data=(
            bytes([0])
            + bytes([0])
            + bytes(authority_pk)
            + bytes([1])
            + bytes(authority_pk)
        ),
    )

    # 3. Create buyer's NFT ATA — authority pays, buyer is owner (no buyer signature)
    ix_create_nft_ata = Instruction(
        program_id=ASSOCIATED_TOKEN_PROGRAM,
        accounts=[
            AccountMeta(pubkey=authority_pk, is_signer=True, is_writable=True),
            AccountMeta(pubkey=buyer_nft_ata, is_signer=False, is_writable=True),
            AccountMeta(pubkey=buyer_pk, is_signer=False, is_writable=False),
            AccountMeta(pubkey=mint_pk, is_signer=False, is_writable=False),
            AccountMeta(pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        ],
        data=bytes([1]),
    )

    # 4. MintTo — 1 token to buyer's ATA
    ix_mint_to = Instruction(
        program_id=TOKEN_PROGRAM_ID,
        accounts=[
            AccountMeta(pubkey=mint_pk, is_signer=False, is_writable=True),
            AccountMeta(pubkey=buyer_nft_ata, is_signer=False, is_writable=True),
            AccountMeta(pubkey=authority_pk, is_signer=True, is_writable=False),
        ],
        data=bytes([7]) + struct.pack("<Q", 1),
    )

    # 5. CreateMetadataAccountV3 — authority pays
    ix_create_metadata = Instruction(
        program_id=METADATA_PROGRAM_ID,
        accounts=[
            AccountMeta(pubkey=metadata_pda, is_signer=False, is_writable=True),
            AccountMeta(pubkey=mint_pk, is_signer=False, is_writable=False),
            AccountMeta(pubkey=authority_pk, is_signer=True, is_writable=False),   # mint authority
            AccountMeta(pubkey=authority_pk, is_signer=True, is_writable=True),    # payer
            AccountMeta(pubkey=authority_pk, is_signer=False, is_writable=False),  # update authority
            AccountMeta(pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=SYSVAR_RENT, is_signer=False, is_writable=False),
        ],
        data=(
            bytes([33])
            + _borsh_str("Alpine Labs Builder Pass")
            + _borsh_str("ALBP")
            + _borsh_str(settings.builder_pass_metadata_uri)
            + struct.pack("<H", 500)            # seller_fee_basis_points = 5%
            + bytes([1])                       # creators: Some
            + struct.pack("<I", 1)             # 1 creator
            + bytes(authority_pk)              # creator pubkey
            + bytes([1])                       # verified = true (authority signs this tx)
            + bytes([100])                     # share = 100%
            + bytes([1])                       # collection: Some
            + bytes([0])                       # verified = false (VerifySizedCollectionItem follows)
            + bytes(collection_mint_pk)
            + bytes([0])                       # uses: None
            + bytes([1])                       # is_mutable = true
            + bytes([0])                       # collection_details: None
        ),
    )

    # 6. CreateMasterEditionV3 — authority pays, max_supply = Some(0)
    ix_create_edition = Instruction(
        program_id=METADATA_PROGRAM_ID,
        accounts=[
            AccountMeta(pubkey=edition_pda, is_signer=False, is_writable=True),
            AccountMeta(pubkey=mint_pk, is_signer=False, is_writable=True),
            AccountMeta(pubkey=authority_pk, is_signer=True, is_writable=False),   # update authority
            AccountMeta(pubkey=authority_pk, is_signer=True, is_writable=False),   # mint authority
            AccountMeta(pubkey=authority_pk, is_signer=True, is_writable=True),    # payer
            AccountMeta(pubkey=metadata_pda, is_signer=False, is_writable=True),
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=SYSVAR_RENT, is_signer=False, is_writable=False),
        ],
        data=bytes([17]) + bytes([1]) + struct.pack("<Q", 0),
    )

    # 7. VerifySizedCollectionItem — authority is collection update authority + payer
    ix_verify_collection = Instruction(
        program_id=METADATA_PROGRAM_ID,
        accounts=[
            AccountMeta(pubkey=metadata_pda, is_signer=False, is_writable=True),
            AccountMeta(pubkey=authority_pk, is_signer=True, is_writable=False),   # collection authority
            AccountMeta(pubkey=authority_pk, is_signer=True, is_writable=True),    # payer
            AccountMeta(pubkey=collection_mint_pk, is_signer=False, is_writable=False),
            AccountMeta(pubkey=collection_metadata_pda, is_signer=False, is_writable=True),
            AccountMeta(pubkey=collection_edition_pda, is_signer=False, is_writable=False),
        ],
        data=bytes([30]),  # VerifySizedCollectionItem
    )

    bh_resp = await _rpc_post("getLatestBlockhash", [{"commitment": "confirmed"}], rpc_url=MAINNET_RPC_URL)
    recent_blockhash = Hash.from_string(bh_resp["result"]["value"]["blockhash"])

    instructions = [
        ix_create_account, ix_init_mint, ix_create_nft_ata,
        ix_mint_to, ix_create_metadata, ix_create_edition, ix_verify_collection,
    ]

    msg = Message.new_with_blockhash(instructions, authority_pk, recent_blockhash)
    tx = Transaction([authority_kp, mint_kp], msg, recent_blockhash)
    tx_b64 = base64.b64encode(bytes(tx)).decode()

    resp = await _rpc_post(
        "sendTransaction",
        [tx_b64, {"encoding": "base64", "skipPreflight": True, "maxRetries": 3}],
        rpc_url=MAINNET_RPC_URL,
    )
    if "error" in resp:
        raise Exception(f"NFT mint sendTransaction failed: {resp['error']}")
    sig = resp["result"]
    _log.info("Server-side NFT mint submitted: mint=%s sig=%s buyer=%s", mint_pk, sig, buyer_wallet)

    for _ in range(30):
        await asyncio.sleep(2)
        conf = await _rpc_post(
            "getSignatureStatuses",
            [[sig], {"searchTransactionHistory": True}],
            rpc_url=MAINNET_RPC_URL,
        )
        status = ((conf.get("result") or {}).get("value") or [None])[0]
        if status:
            if status.get("err") is not None:
                raise Exception(f"NFT mint tx failed on-chain: {status['err']}")
            if status.get("confirmationStatus") in ("confirmed", "finalized"):
                _log.info("Server-side NFT mint confirmed: mint=%s buyer=%s", mint_pk, buyer_wallet)
                return str(mint_pk), sig

    raise Exception("NFT mint tx not confirmed within 60 seconds")


async def submit_mint_transaction(signed_tx_b64: str, mint_pk_str: str, buyer_wallet: str) -> str:
    """Complete backend signatures, submit the combined mint tx, and return the confirmed signature."""
    db = get_supabase_admin()
    pending_res = (
        db.table("builder_pass_pending_mints")
        .select("*")
        .eq("mint_pubkey", mint_pk_str)
        .maybe_single()
        .execute()
    )
    pending = pending_res.data
    if not pending:
        raise ValueError("Mint transaction expired; prepare a new Builder Pass mint")
    if pending["buyer_wallet"] != buyer_wallet:
        raise ValueError("Mint transaction buyer mismatch")

    expires_at = datetime.fromisoformat(pending["expires_at"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) >= expires_at:
        db.table("builder_pass_pending_mints").delete().eq("mint_pubkey", mint_pk_str).execute()
        raise ValueError("Mint transaction expired; prepare a new Builder Pass mint")

    tx = Transaction.from_bytes(base64.b64decode(signed_tx_b64))
    if bytes(tx.message) != base64.b64decode(pending["message_b64"]):
        raise ValueError("Signed mint transaction does not match prepared transaction")
    if buyer_wallet not in {str(key) for key in tx.message.signer_keys()}:
        raise ValueError("Buyer is not a required signer for mint transaction")
    verify_results = tx.verify_with_results()
    if not verify_results or not verify_results[0]:
        raise ValueError("Buyer signature missing or invalid")

    authority_kp = SoldersKeypair.from_bytes(bytes(json.loads(_settings.builder_pass_authority_keypair)))
    mint_kp = _decrypt_builder_pass_mint_keypair(pending["encrypted_mint_keypair"])
    recent_blockhash = Hash.from_string(pending["recent_blockhash"])
    tx.partial_sign([authority_kp, mint_kp], recent_blockhash)
    if not tx.is_signed():
        raise ValueError("Mint transaction is missing required signatures")
    tx_b64 = base64.b64encode(bytes(tx)).decode()

    resp = await _rpc_post(
        "sendTransaction",
        [tx_b64, {"encoding": "base64", "skipPreflight": False, "preflightCommitment": "confirmed", "maxRetries": 3}],
        rpc_url=MAINNET_RPC_URL,
    )
    if "error" in resp:
        raise Exception(f"sendTransaction failed: {resp['error']}")
    sig = resp["result"]
    _log.info("Combined mint tx submitted: mint=%s sig=%s buyer=%s", mint_pk_str, sig, buyer_wallet)

    for _ in range(30):
        await asyncio.sleep(2)
        conf = await _rpc_post(
            "getSignatureStatuses",
            [[sig], {"searchTransactionHistory": True}],
            rpc_url=MAINNET_RPC_URL,
        )
        status = ((conf.get("result") or {}).get("value") or [None])[0]
        if status:
            if status.get("err") is not None:
                raise Exception(f"Combined mint tx failed on-chain: {status['err']}")
            if status.get("confirmationStatus") in ("confirmed", "finalized"):
                db.table("builder_pass_pending_mints").delete().eq("mint_pubkey", mint_pk_str).execute()
                return sig

    raise Exception("Combined mint tx not confirmed within 60 seconds")


async def build_usdc_transfer_transaction(buyer_wallet: str, amount_raw: int) -> str:
    """
    Build an unsigned payment transaction the wallet signs to buy a Builder Pass.
    Contains two buyer-only instructions:
      1. Idempotent create treasury USDC ATA (no-op if exists)
      2. USDC transfer: buyer → treasury
    Buyer is the only signer.
    """
    settings = _settings
    buyer_pk = Pubkey.from_string(buyer_wallet)
    usdc_mint_pk = Pubkey.from_string(USDC_MINT)
    treasury_pk = Pubkey.from_string(settings.builder_pass_treasury)
    authority_pk = Pubkey.from_string(builder_pass_authority_pubkey())

    buyer_usdc_ata = _find_ata(buyer_pk, usdc_mint_pk)
    treasury_usdc_ata = _find_ata(treasury_pk, usdc_mint_pk)

    # 1. Idempotent create treasury ATA — no-op if already exists
    create_treasury_ata_ix = Instruction(
        program_id=ASSOCIATED_TOKEN_PROGRAM,
        accounts=[
            AccountMeta(pubkey=buyer_pk, is_signer=True, is_writable=True),
            AccountMeta(pubkey=treasury_usdc_ata, is_signer=False, is_writable=True),
            AccountMeta(pubkey=treasury_pk, is_signer=False, is_writable=False),
            AccountMeta(pubkey=usdc_mint_pk, is_signer=False, is_writable=False),
            AccountMeta(pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        ],
        data=bytes([1]),
    )

    # 2. USDC transfer: buyer → treasury
    transfer_ix = Instruction(
        program_id=TOKEN_PROGRAM_ID,
        accounts=[
            AccountMeta(pubkey=buyer_usdc_ata, is_signer=False, is_writable=True),
            AccountMeta(pubkey=treasury_usdc_ata, is_signer=False, is_writable=True),
            AccountMeta(pubkey=buyer_pk, is_signer=True, is_writable=False),
        ],
        data=bytes([3]) + struct.pack("<Q", amount_raw),
    )

    instructions = [create_treasury_ata_ix, transfer_ix]
    if settings.builder_pass_sol_fee_lamports > 0:
        instructions.append(
            Instruction(
                program_id=SYSTEM_PROGRAM_ID,
                accounts=[
                    AccountMeta(pubkey=buyer_pk, is_signer=True, is_writable=True),
                    AccountMeta(pubkey=authority_pk, is_signer=False, is_writable=True),
                ],
                data=struct.pack("<IQ", 2, settings.builder_pass_sol_fee_lamports),
            )
        )

    bh_resp = await _rpc_post("getLatestBlockhash", [{"commitment": "confirmed"}], rpc_url=MAINNET_RPC_URL)
    recent_blockhash = Hash.from_string(bh_resp["result"]["value"]["blockhash"])
    msg = Message.new_with_blockhash(instructions, buyer_pk, recent_blockhash)
    tx = Transaction.new_unsigned(msg)
    tx_b64 = base64.b64encode(bytes(tx)).decode()

    # Pre-flight: simulate server-side so any RPC/account error surfaces here
    # rather than as a cryptic "could not be simulated" in the wallet.
    sim = await _rpc_post(
        "simulateTransaction",
        [tx_b64, {"encoding": "base64", "sigVerify": False, "commitment": "confirmed"}],
        rpc_url=MAINNET_RPC_URL,
    )
    sim_err = (sim.get("result") or {}).get("value", {}).get("err")
    if sim_err is not None:
        logs = (sim.get("result") or {}).get("value", {}).get("logs", [])
        _log.error("USDC transfer pre-flight failed err=%s logs=%s", sim_err, logs)
        # InvalidAccountData on the transfer instruction means the buyer has no USDC token account
        instr_err = sim_err.get("InstructionError") if isinstance(sim_err, dict) else None
        if isinstance(instr_err, list) and len(instr_err) >= 2 and instr_err[1] == "InvalidAccountData":
            raise ValueError("Your wallet does not have a USDC token account. Please add USDC to your wallet before purchasing a Builder Pass.")
        raise Exception(f"USDC transfer simulation failed: {sim_err} — logs: {logs[-3:] if logs else []}")

    return tx_b64


async def fetch_confirmed_transaction(
    tx_signature: str,
    rpc_url: str = MAINNET_RPC_URL,
    commitment: str = "confirmed",
) -> dict[str, Any]:
    """Fetch a confirmed transaction as jsonParsed RPC data.

    Use commitment='finalized' for trust-critical operations (prize claim,
    organizer refund) where a fork/reorg flipping DB state would be a problem.
    'confirmed' is fine for everything else.
    """
    # finalized takes ~15-30s on mainnet; give it up to 60s. confirmed is fast.
    max_retries = 30 if commitment == "finalized" else 5
    sleep_secs = 2 if commitment == "finalized" else 1
    for _ in range(max_retries):
        resp = await _rpc_post(
            "getTransaction",
            [tx_signature, {"encoding": "jsonParsed", "commitment": commitment, "maxSupportedTransactionVersion": 0}],
            rpc_url=rpc_url,
        )
        tx_data = resp.get("result")
        if tx_data:
            if tx_data.get("meta", {}).get("err") is not None:
                raise Exception(f"Confirmed transaction has on-chain error: {tx_data['meta']['err']}")
            return tx_data
        await asyncio.sleep(sleep_secs)
    raise Exception(f"Confirmed transaction not found: {tx_signature}")


def parse_treasury_usdc_delta(tx_data: dict[str, Any], treasury_wallet: str) -> int:
    """Return the raw USDC increase for the configured Builder Pass treasury owner."""
    meta = tx_data.get("meta") or {}

    def summed_balances(key: str) -> int:
        total = 0
        for bal in meta.get(key) or []:
            if bal.get("mint") != USDC_MINT or bal.get("owner") != treasury_wallet:
                continue
            amount = (bal.get("uiTokenAmount") or {}).get("amount") or "0"
            total += int(amount)
        return total

    return summed_balances("postTokenBalances") - summed_balances("preTokenBalances")


def parse_wallet_sol_delta(tx_data: dict[str, Any], wallet: str) -> int:
    """Return the lamport balance delta for a transaction account."""
    message = _tx_message(tx_data)
    keys = message.get("accountKeys") or []
    pre = (tx_data.get("meta") or {}).get("preBalances") or []
    post = (tx_data.get("meta") or {}).get("postBalances") or []

    for idx, acc in enumerate(keys):
        pubkey = acc.get("pubkey", "") if isinstance(acc, dict) else str(acc)
        if pubkey == wallet and idx < len(pre) and idx < len(post):
            return int(post[idx]) - int(pre[idx])
    return 0


def _owner_token_delta(tx_data: dict[str, Any], mint: str, owner: str) -> int:
    meta = tx_data.get("meta") or {}

    def total(key: str) -> int:
        amount = 0
        for bal in meta.get(key) or []:
            if bal.get("mint") == mint and bal.get("owner") == owner:
                amount += int((bal.get("uiTokenAmount") or {}).get("amount") or "0")
        return amount

    return total("postTokenBalances") - total("preTokenBalances")


async def verify_registration_fee_payment_on_chain(
    tx_signature: str,
    payer_wallet: str,
    expected_amount: int,
) -> bool:
    """Confirm the registration tx paid the configured USDC fee to the treasury."""
    if expected_amount <= 0:
        return True
    treasury = _settings.builder_pass_treasury
    if not treasury:
        _log.error("Registration fee is enabled but BUILDER_PASS_TREASURY is not configured")
        return False

    tx_data = await fetch_confirmed_transaction(tx_signature, rpc_url=RPC_URL)
    if payer_wallet not in _tx_signers(tx_data):
        return False

    treasury_delta = _owner_token_delta(tx_data, ESCROW_USDC_MINT, treasury)
    payer_delta = _owner_token_delta(tx_data, ESCROW_USDC_MINT, payer_wallet)
    _log.info(
        "Registration fee check: payer_delta=%d treasury_delta=%d expected=%d",
        payer_delta,
        treasury_delta,
        expected_amount,
    )
    return treasury_delta >= expected_amount and payer_delta <= -expected_amount


def validate_builder_pass_mint_transaction(
    tx_data: dict[str, Any],
    buyer_wallet: str,
    mint_pubkey: str,
    expected_price_usdc_raw: int,
    treasury_wallet: str,
) -> tuple[bool, str]:
    """Validate that a confirmed tx actually minted the requested Builder Pass to the buyer."""
    if buyer_wallet not in _tx_signers(tx_data):
        return False, "buyer did not sign transaction"
    if mint_pubkey not in _tx_signers(tx_data):
        return False, "mint account did not sign transaction"

    treasury_delta = parse_treasury_usdc_delta(tx_data, treasury_wallet)
    if treasury_delta != expected_price_usdc_raw:
        return False, f"treasury USDC received {treasury_delta}, expected {expected_price_usdc_raw}"

    nft_delta = _owner_token_delta(tx_data, mint_pubkey, buyer_wallet)
    if nft_delta != 1:
        return False, f"buyer NFT balance delta was {nft_delta}, expected 1"

    account_keys = _tx_account_keys(tx_data)
    if mint_pubkey not in account_keys:
        return False, "mint account missing from transaction"

    mint_pk = Pubkey.from_string(mint_pubkey)
    metadata_pda, _ = Pubkey.find_program_address(
        [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(mint_pk)],
        METADATA_PROGRAM_ID,
    )

    if not _has_program_instruction(tx_data, str(METADATA_PROGRAM_ID), bytes([33]), [mint_pubkey]):
        return False, "CreateMetadataAccountV3 instruction missing"
    if not _has_program_instruction(tx_data, str(METADATA_PROGRAM_ID), bytes([17]), [mint_pubkey]):
        return False, "CreateMasterEditionV3 instruction missing"
    if not _has_program_instruction(tx_data, str(METADATA_PROGRAM_ID), bytes([30]), [str(metadata_pda)]):
        return False, "VerifySizedCollectionItem instruction missing"

    return True, "ok"


async def submit_and_confirm_transaction(signed_tx_b64: str) -> str:
    """Submit a wallet-signed transaction to mainnet and return its base58 signature."""
    resp = await _rpc_post(
        "sendTransaction",
        [signed_tx_b64, {"encoding": "base64", "preflightCommitment": "confirmed", "skipPreflight": False}],
        rpc_url=MAINNET_RPC_URL,
    )
    if "error" in resp:
        raise Exception(f"sendTransaction failed: {resp['error']}")
    sig = resp["result"]  # base58 signature string

    for _ in range(30):
        await asyncio.sleep(2)
        conf = await _rpc_post(
            "getSignatureStatuses",
            [[sig], {"searchTransactionHistory": True}],
            rpc_url=MAINNET_RPC_URL,
        )
        status = ((conf.get("result") or {}).get("value") or [None])[0]
        if status:
            if status.get("err") is not None:
                raise Exception(f"Transaction failed on-chain: {status['err']}")
            if status.get("confirmationStatus") in ("confirmed", "finalized"):
                return sig
    raise Exception("Transaction not confirmed within 60 seconds")


async def verify_usdc_payment(tx_signature: str, buyer_wallet: str, expected_amount: int) -> dict[str, Any] | None:
    """Return confirmed tx data when buyer paid the configured treasury in USDC."""
    settings = _settings
    treasury = settings.builder_pass_treasury

    resp = await _rpc_post(
        "getTransaction",
        [tx_signature, {"encoding": "jsonParsed", "commitment": "confirmed", "maxSupportedTransactionVersion": 0}],
        rpc_url=MAINNET_RPC_URL,
    )
    tx_data = resp.get("result")
    if not tx_data or tx_data.get("meta", {}).get("err") is not None:
        return None

    # Buyer must have signed
    message = tx_data.get("transaction", {}).get("message", {})
    signer_pubkeys = {
        acc.get("pubkey", "")
        for acc in message.get("accountKeys", [])
        if isinstance(acc, dict) and acc.get("signer")
    }
    if buyer_wallet not in signer_pubkeys:
        return None

    # Treasury USDC balance must have increased by at least expected_amount
    meta = tx_data.get("meta", {})
    pre_by_owner: dict[str, int] = {}
    post_by_owner: dict[str, int] = {}
    for bal in (meta.get("preTokenBalances") or []):
        if bal.get("mint") == USDC_MINT:
            pre_by_owner[bal.get("owner", "")] = int(bal.get("uiTokenAmount", {}).get("amount", 0))
    for bal in (meta.get("postTokenBalances") or []):
        if bal.get("mint") == USDC_MINT:
            post_by_owner[bal.get("owner", "")] = int(bal.get("uiTokenAmount", {}).get("amount", 0))

    increase = post_by_owner.get(treasury, 0) - pre_by_owner.get(treasury, 0)
    _log.info("USDC payment check: treasury increase=%d expected=%d", increase, expected_amount)
    return tx_data if increase >= expected_amount else None


async def verify_builder_pass_holder(wallet_address: str) -> bool:
    """Return True if the wallet holds an Alpine Labs Builder Pass NFT."""
    collection = _settings.builder_pass_collection_mint
    if not collection:
        return False
    for token_program in (TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID):
        resp = await _rpc_post(
            "getTokenAccountsByOwner",
            [wallet_address, {"programId": str(token_program)}, {"encoding": "jsonParsed", "commitment": "confirmed"}],
            rpc_url=MAINNET_RPC_URL,
        )
        for acct in (resp.get("result", {}).get("value") or []):
            info = acct.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
            if info.get("tokenAmount", {}).get("uiAmount", 0) == 1:
                coll_key, _ = await _fetch_nft_collection(info.get("mint", ""))
                if coll_key == collection:
                    return True
    return False


async def verify_builder_pass_mint_on_chain(tx_signature: str, buyer_wallet: str) -> bool:
    """Confirm the mint transaction landed on-chain and the buyer signed it."""
    resp = await _rpc_post(
        "getTransaction",
        [tx_signature, {"encoding": "jsonParsed", "commitment": "confirmed", "maxSupportedTransactionVersion": 0}],
        rpc_url=MAINNET_RPC_URL,
    )
    tx_data = resp.get("result")
    if not tx_data or tx_data.get("meta", {}).get("err") is not None:
        return False
    message = tx_data.get("transaction", {}).get("message", {})
    signer_pubkeys = {
        acc.get("pubkey", "")
        for acc in message.get("accountKeys", [])
        if isinstance(acc, dict) and acc.get("signer")
    }
    return buyer_wallet in signer_pubkeys


def _parse_metadata_collection(data: bytes) -> tuple[str | None, bool]:
    """
    Proper Borsh parser for a Metaplex token metadata account.
    Layout: key(1) + update_authority(32) + mint(32) + name(str) + symbol(str) +
            uri(str) + seller_fee_bps(u16) + creators(Option<Vec<Creator>>) +
            primary_sale(bool) + is_mutable(bool) + edition_nonce(Option<u8>) +
            token_standard(Option<u8>) + collection(Option<Collection>)
    Returns (collection_key_b58, verified) or (None, False) on any parse error.
    """
    try:
        pos = 1 + 32 + 32  # key + update_authority + mint
        for _ in range(3):  # name, symbol, uri — each is u32 len prefix + bytes
            length = struct.unpack_from("<I", data, pos)[0]
            pos += 4 + length
        pos += 2  # seller_fee_basis_points (u16)
        # creators: Option<Vec<Creator>>  Creator = pubkey(32) + verified(1) + share(1)
        if data[pos]:
            pos += 1
            count = struct.unpack_from("<I", data, pos)[0]
            pos += 4 + count * 34
        else:
            pos += 1
        pos += 2  # primary_sale_happened(bool) + is_mutable(bool)
        pos += 2 if data[pos] else 1  # edition_nonce: Option<u8>
        pos += 2 if data[pos] else 1  # token_standard: Option<u8>
        # collection: Option<Collection>  = verified(bool) + key(Pubkey)
        if data[pos]:
            pos += 1
            verified = bool(data[pos])
            key = str(Pubkey.from_bytes(data[pos + 1: pos + 33]))
            return key, verified
        return None, False
    except Exception:
        return None, False


_TOKEN22_MINT_BASE = 82   # standard SPL Token mint state size
_TOKEN_GROUP_MEMBER_TYPE = 29  # Token-2022 ExtensionType::TokenGroupMember


def _parse_token22_group(data: bytes) -> str | None:
    """
    Parse a Token-2022 mint account's TLV extension list and return the
    tokenGroupMember.group pubkey, or None if not found.
    Layout after base mint (82 bytes): account_type(1) then TLV entries.
    Each TLV: type(u16 LE) + length(u16 LE) + data(length bytes).
    TokenGroupMember data: mint(32) + group(32) + member_number(u32).
    """
    if len(data) <= _TOKEN22_MINT_BASE:
        return None
    pos = _TOKEN22_MINT_BASE + 1  # skip base state + account_type byte
    while pos + 4 <= len(data):
        ext_type = struct.unpack_from("<H", data, pos)[0]
        ext_len = struct.unpack_from("<H", data, pos + 2)[0]
        pos += 4
        if ext_type == _TOKEN_GROUP_MEMBER_TYPE and ext_len >= 64:
            try:
                return str(Pubkey.from_bytes(data[pos + 32: pos + 64]))
            except Exception:
                return None
        pos += ext_len
    return None


async def _fetch_nft_collection(mint_str: str) -> tuple[str | None, bool]:
    """
    Return (collection_key, verified) for a mint.
    1. jsonParsed Token-2022 extensions (some RPC providers parse these)
    2. Raw base64 TLV parse (public mainnet RPC often doesn't parse Token-2022)
    3. Metaplex metadata PDA fallback for standard SPL Token NFTs
    """
    # --- Token-2022 jsonParsed ---
    try:
        resp = await _rpc_post(
            "getAccountInfo",
            [mint_str, {"encoding": "jsonParsed", "commitment": "confirmed"}],
            rpc_url=MAINNET_RPC_URL,
        )
        value = resp.get("result", {}).get("value") or {}
        extensions = value.get("data", {}).get("parsed", {}).get("info", {}).get("extensions", [])
        for ext in extensions:
            if ext.get("extension") == "tokenGroupMember":
                group = (ext.get("state") or {}).get("group")
                if group:
                    return group, True
    except Exception:
        pass

    # --- Token-2022 raw TLV (public RPC fallback) ---
    try:
        resp = await _rpc_post(
            "getAccountInfo",
            [mint_str, {"encoding": "base64", "commitment": "confirmed"}],
            rpc_url=MAINNET_RPC_URL,
        )
        value = resp.get("result", {}).get("value") or {}
        raw_list = value.get("data") or []
        if raw_list:
            raw_bytes = base64.b64decode(raw_list[0])
            _log.info("Token-2022 TLV raw data for %s: len=%d bytes[82:86]=%s",
                      mint_str, len(raw_bytes), raw_bytes[82:90].hex() if len(raw_bytes) > 90 else "short")
            group = _parse_token22_group(raw_bytes)
            if group:
                _log.info("Token-2022 TLV group found for mint %s: %s", mint_str, group)
                return group, True
            _log.warning("Token-2022 TLV: no tokenGroupMember found in %d bytes for mint %s", len(raw_bytes), mint_str)
        else:
            _log.warning("Token-2022 base64: no data returned for mint %s", mint_str)
    except Exception as exc:
        _log.warning("Token-2022 TLV parse failed for %s: %s", mint_str, exc)

    # --- Metaplex metadata PDA ---
    try:
        mint = Pubkey.from_string(mint_str)
    except ValueError:
        return None, False
    metadata_pda, _ = Pubkey.find_program_address(
        [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(mint)],
        METADATA_PROGRAM_ID,
    )
    resp = await _rpc_post(
        "getAccountInfo",
        [str(metadata_pda), {"encoding": "base64", "commitment": "confirmed"}],
        rpc_url=MAINNET_RPC_URL,
    )
    if not (resp.get("result", {}).get("value") or {}):
        return None, False
    data = base64.b64decode(resp["result"]["value"]["data"][0])
    return _parse_metadata_collection(data)


async def verify_seeker_genesis_holder(wallet_address: str) -> bool:
    """
    Verifies that the wallet holds at least one Seeker Genesis NFT.
    Always checks mainnet. Queries both SPL Token and Token-2022 programs.
    """
    _log.info("Genesis check starting for wallet %s (configured collection: %s)", wallet_address, GENESIS_COLLECTION)
    for token_program in (TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID):
        resp = await _rpc_post(
            "getTokenAccountsByOwner",
            [
                wallet_address,
                {"programId": str(token_program)},
                {"encoding": "jsonParsed", "commitment": "confirmed"},
            ],
            rpc_url=MAINNET_RPC_URL,
        )
        accounts = resp.get("result", {}).get("value") or []
        _log.info("  program=%s  token accounts found: %d", token_program, len(accounts))
        for acct in accounts:
            info = acct.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
            amount = info.get("tokenAmount", {}).get("uiAmount", 0)
            mint_str = info.get("mint", "")
            _log.info("    mint=%s  uiAmount=%s", mint_str, amount)
            if amount == 1:
                collection_key, _verified = await _fetch_nft_collection(mint_str)
                _log.info("    -> collection_key=%s  matches=%s", collection_key, collection_key == GENESIS_COLLECTION)
                if collection_key == GENESIS_COLLECTION:
                    return True
    _log.warning("Genesis check FAILED for wallet %s — no matching NFT found", wallet_address)
    return False




MEMO_PROGRAM_ID = Pubkey.from_string("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr")


async def build_vote_transaction(
    voter_wallet: str,
    project_pda: str | None,
    hackathon_pda: str | None,
    vote_weight_bps: int,
) -> str:
    """
    Build an unsigned Solana transaction for casting a vote.

    When the project has no on-chain PDA the wallet is connected to mainnet,
    so we use a memo instruction with a mainnet blockhash — the memo program
    exists on every cluster, passes simulation, and gives a real signature.

    When the project has a real on-chain PDA we use the voting program on devnet.
    """
    voter = Pubkey.from_string(voter_wallet)

    instruction = Instruction(
        program_id=MEMO_PROGRAM_ID,
        accounts=[AccountMeta(pubkey=voter, is_signer=True, is_writable=False)],
        data=f"seeker-vote:bps={vote_weight_bps}".encode(),
    )
    bh_resp = await _rpc_post("getLatestBlockhash", [{"commitment": "confirmed"}], rpc_url=MAINNET_RPC_URL)

    blockhash_str = bh_resp["result"]["value"]["blockhash"]
    recent_blockhash = Hash.from_string(blockhash_str)
    msg = Message.new_with_blockhash([instruction], voter, recent_blockhash)
    tx = Transaction.new_unsigned(msg)
    return base64.b64encode(bytes(tx)).decode()


async def verify_transaction_on_chain(tx_signature: str, project_pda: str | None, voter_wallet: str) -> bool:
    """
    Confirm a vote transaction landed on-chain and the voter signed it.
    All vote transactions use the memo program on mainnet.
    """
    resp = await _rpc_post(
        "getTransaction",
        [tx_signature, {"encoding": "jsonParsed", "commitment": "confirmed", "maxSupportedTransactionVersion": 0}],
        rpc_url=MAINNET_RPC_URL,
    )
    tx_data = resp.get("result")
    if not tx_data:
        return False
    if tx_data.get("meta", {}).get("err") is not None:
        return False

    message = tx_data.get("transaction", {}).get("message", {})
    for acc in message.get("accountKeys", []):
        if isinstance(acc, dict):
            if acc.get("pubkey") == voter_wallet and acc.get("signer"):
                return True
        else:
            if str(acc) == voter_wallet:
                return True
    return False


async def build_create_escrow_transaction(
    organizer_wallet: str,
    hackathon_id_str: str,
    prize_usdc: int,
    voting_start_ts: int,
    voting_end_ts: int,
    presign_platform_admin: bool = True,
) -> tuple[str, str]:
    """
    Build an unsigned create_hackathon transaction for the escrow program.
    Returns (base64_tx, escrow_pda_str).
    Instruction: create_hackathon(hackathon_id: [u8;16], prize_usdc: u64, voting_start: i64, voting_end: i64)
    """
    organizer = Pubkey.from_string(organizer_wallet)
    platform_admin_kp = _escrow_platform_admin_keypair()
    platform_admin = platform_admin_kp.pubkey()
    usdc_mint_pk = Pubkey.from_string(ESCROW_USDC_MINT)
    escrow_program = Pubkey.from_string(ESCROW_PROGRAM)

    hackathon_id_bytes = _uuid.UUID(hackathon_id_str).bytes

    # seeds = [b"hackathon_escrow", hackathon_id]  (from lib.rs CreateHackathon constraint)
    escrow_pda, _ = Pubkey.find_program_address(
        [b"hackathon_escrow", hackathon_id_bytes],
        escrow_program,
    )
    vault = _find_ata(escrow_pda, usdc_mint_pk)
    organizer_usdc_ata = _find_ata(organizer, usdc_mint_pk)

    SYSVAR_RENT = Pubkey.from_string("SysvarRent111111111111111111111111111111111")

    discriminator = _anchor_discriminator("create_hackathon")

    ix_data = (
        discriminator
        + hackathon_id_bytes
        + struct.pack("<Q", prize_usdc)
        + struct.pack("<q", voting_start_ts)
        + struct.pack("<q", voting_end_ts)
    )

    instruction = Instruction(
        program_id=escrow_program,
        accounts=[
            AccountMeta(pubkey=organizer, is_signer=True, is_writable=True),
            AccountMeta(pubkey=platform_admin, is_signer=True, is_writable=False),
            AccountMeta(pubkey=usdc_mint_pk, is_signer=False, is_writable=False),
            AccountMeta(pubkey=escrow_pda, is_signer=False, is_writable=True),
            AccountMeta(pubkey=vault, is_signer=False, is_writable=True),
            AccountMeta(pubkey=organizer_usdc_ata, is_signer=False, is_writable=True),
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=ASSOCIATED_TOKEN_PROGRAM, is_signer=False, is_writable=False),
            AccountMeta(pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=SYSVAR_RENT, is_signer=False, is_writable=False),
        ],
        data=ix_data,
    )

    bh_resp = await _rpc_post("getLatestBlockhash", [{"commitment": "confirmed"}], rpc_url=MAINNET_RPC_URL)
    blockhash_str = bh_resp["result"]["value"]["blockhash"]
    recent_blockhash = Hash.from_string(blockhash_str)

    msg = Message.new_with_blockhash([instruction], organizer, recent_blockhash)
    tx = Transaction.new_unsigned(msg)
    if presign_platform_admin:
        tx.partial_sign([platform_admin_kp], recent_blockhash)
    tx_b64 = base64.b64encode(bytes(tx)).decode()

    _log.info(
        "escrow tx accounts: organizer=%s platform_admin=%s usdc_mint=%s escrow_pda=%s vault=%s organizer_usdc_ata=%s token_program=%s assoc_token=%s system=%s rent=%s program=%s",
        organizer, platform_admin, usdc_mint_pk, escrow_pda, vault, organizer_usdc_ata,
        TOKEN_PROGRAM_ID, ASSOCIATED_TOKEN_PROGRAM, SYSTEM_PROGRAM_ID, SYSVAR_RENT, escrow_program,
    )

    sim_resp = await _rpc_post(
        "simulateTransaction",
        [tx_b64, {"encoding": "base64", "commitment": "confirmed", "replaceRecentBlockhash": True}],
        rpc_url=MAINNET_RPC_URL,
    )
    sim_result = sim_resp.get("result", {}).get("value", {})
    sim_logs = sim_result.get("logs") or []
    sim_err = sim_result.get("err")
    _log.info("escrow simulation result: err=%s logs=%s", sim_err, sim_logs)
    if sim_err:
        anchor_msg = next(
            (line.split("Error Message: ", 1)[1] for line in sim_logs if "Error Message: " in line),
            None,
        )
        raise ValueError(anchor_msg or f"Transaction simulation failed: {sim_err}")

    return tx_b64, str(escrow_pda)


def _expected_create_escrow_instruction(
    organizer_wallet: str,
    hackathon_id_str: str,
    prize_usdc: int,
    voting_start_ts: int,
    voting_end_ts: int,
) -> tuple[Instruction, str]:
    organizer = Pubkey.from_string(organizer_wallet)
    platform_admin = _escrow_platform_admin_keypair().pubkey()
    usdc_mint_pk = Pubkey.from_string(ESCROW_USDC_MINT)
    escrow_program = Pubkey.from_string(ESCROW_PROGRAM)
    hackathon_id_bytes = _uuid.UUID(hackathon_id_str).bytes
    escrow_pda, _ = Pubkey.find_program_address(
        [b"hackathon_escrow", hackathon_id_bytes],
        escrow_program,
    )
    vault = _find_ata(escrow_pda, usdc_mint_pk)
    organizer_usdc_ata = _find_ata(organizer, usdc_mint_pk)
    sysvar_rent = Pubkey.from_string("SysvarRent111111111111111111111111111111111")
    ix_data = (
        _anchor_discriminator("create_hackathon")
        + hackathon_id_bytes
        + struct.pack("<Q", prize_usdc)
        + struct.pack("<q", voting_start_ts)
        + struct.pack("<q", voting_end_ts)
    )
    instruction = Instruction(
        program_id=escrow_program,
        accounts=[
            AccountMeta(pubkey=organizer, is_signer=True, is_writable=True),
            AccountMeta(pubkey=platform_admin, is_signer=True, is_writable=False),
            AccountMeta(pubkey=usdc_mint_pk, is_signer=False, is_writable=False),
            AccountMeta(pubkey=escrow_pda, is_signer=False, is_writable=True),
            AccountMeta(pubkey=vault, is_signer=False, is_writable=True),
            AccountMeta(pubkey=organizer_usdc_ata, is_signer=False, is_writable=True),
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=ASSOCIATED_TOKEN_PROGRAM, is_signer=False, is_writable=False),
            AccountMeta(pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=sysvar_rent, is_signer=False, is_writable=False),
        ],
        data=ix_data,
    )
    return instruction, str(escrow_pda)


def _validate_create_escrow_signed_tx(
    tx: Transaction,
    organizer_wallet: str,
    hackathon_id_str: str,
    escrow_pubkey: str,
    prize_usdc: int,
    voting_start_ts: int,
    voting_end_ts: int,
) -> None:
    expected_ix, expected_escrow = _expected_create_escrow_instruction(
        organizer_wallet,
        hackathon_id_str,
        prize_usdc,
        voting_start_ts,
        voting_end_ts,
    )
    if escrow_pubkey != expected_escrow:
        raise ValueError("Escrow pubkey does not match expected PDA")

    signer_keys = list(tx.message.signer_keys())
    organizer_pk = Pubkey.from_string(organizer_wallet)
    platform_admin = _escrow_platform_admin_keypair().pubkey()
    if organizer_pk not in signer_keys:
        raise ValueError("Organizer is not a required signer")
    if platform_admin not in signer_keys:
        raise ValueError("Platform admin is not a required signer")

    verify_results = list(tx.verify_with_results())
    organizer_index = signer_keys.index(organizer_pk)
    if not verify_results or not verify_results[organizer_index]:
        raise ValueError("Organizer signature missing or invalid")

    account_keys = list(tx.message.account_keys)
    expected_accounts = [meta.pubkey for meta in expected_ix.accounts]
    matching_instructions = []
    for compiled_ix in tx.message.instructions:
        program_id = account_keys[int(compiled_ix.program_id_index)]
        accounts = [account_keys[int(i)] for i in compiled_ix.accounts]
        data = bytes(compiled_ix.data)
        if program_id == expected_ix.program_id:
            matching_instructions.append((accounts, data))

    if len(matching_instructions) != 1:
        raise ValueError("Expected exactly one create_hackathon instruction")
    accounts, data = matching_instructions[0]
    if accounts != expected_accounts:
        raise ValueError("Create hackathon accounts do not match expected escrow transaction")
    if data != bytes(expected_ix.data):
        raise ValueError("Create hackathon instruction data does not match draft hackathon")


async def cosign_and_submit_create_escrow_transaction(
    signed_tx_b64: str,
    organizer_wallet: str,
    hackathon_id_str: str,
    escrow_pubkey: str,
    prize_usdc: int,
    voting_start_ts: int,
    voting_end_ts: int,
) -> str:
    tx = Transaction.from_bytes(base64.b64decode(signed_tx_b64))
    _validate_create_escrow_signed_tx(
        tx,
        organizer_wallet,
        hackathon_id_str,
        escrow_pubkey,
        prize_usdc,
        voting_start_ts,
        voting_end_ts,
    )
    platform_admin_kp = _escrow_platform_admin_keypair()
    tx.partial_sign([platform_admin_kp], tx.message.recent_blockhash)
    if not tx.is_signed():
        raise ValueError("Create escrow transaction is missing required signatures")
    tx_b64 = base64.b64encode(bytes(tx)).decode()
    return await submit_and_confirm_transaction(tx_b64)


async def build_release_transaction(
    organizer_wallet: str,
    hackathon_id_str: str,  # UUID string — converted to 16-byte seed
    escrow_pda: str,
    winner_wallet: str,
) -> str:
    """
    Build an unsigned release_prize transaction for the organizer to sign.
    Transfers 100% of the USDC prize pool from the escrow vault to the winner's USDC ATA.
    Returns base64-encoded transaction.
    """
    organizer = Pubkey.from_string(organizer_wallet)
    escrow = Pubkey.from_string(escrow_pda)
    winner = Pubkey.from_string(winner_wallet)
    usdc_mint = Pubkey.from_string(ESCROW_USDC_MINT)
    escrow_program = Pubkey.from_string(ESCROW_PROGRAM)

    # Vault: ATA owned by the escrow PDA (holds the USDC prize pool)
    vault = _find_ata(escrow, usdc_mint)
    # Winner's USDC ATA (must already exist on-chain)
    winner_usdc_ata = _find_ata(winner, usdc_mint)

    hackathon_id_bytes = _uuid.UUID(hackathon_id_str).bytes  # 16 bytes, standard UUID order

    # sha256("global:release_prize")[:8]
    discriminator = bytes([0x55, 0x53, 0x76, 0x70, 0xca, 0x15, 0x68, 0xd0])

    # Instruction data layout:
    #   [discriminator 8B] [hackathon_id 16B] [winner_share_bps Vec<u16>: 4B len + 2B each]
    share_data = struct.pack("<I", 1) + struct.pack("<H", 10_000)  # 100% (10000 bps) to winner
    ix_data = discriminator + hackathon_id_bytes + share_data

    instruction = Instruction(
        program_id=escrow_program,
        accounts=[
            AccountMeta(pubkey=organizer, is_signer=True, is_writable=True),
            AccountMeta(pubkey=usdc_mint, is_signer=False, is_writable=False),
            AccountMeta(pubkey=escrow, is_signer=False, is_writable=True),
            AccountMeta(pubkey=vault, is_signer=False, is_writable=True),
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
            # Winner USDC ATA in remaining_accounts
            AccountMeta(pubkey=winner_usdc_ata, is_signer=False, is_writable=True),
        ],
        data=ix_data,
    )

    bh_resp = await _rpc_post("getLatestBlockhash", [{"commitment": "confirmed"}])
    blockhash_str = bh_resp["result"]["value"]["blockhash"]
    recent_blockhash = Hash.from_string(blockhash_str)

    msg = Message.new_with_blockhash([instruction], organizer, recent_blockhash)
    tx = Transaction.new_unsigned(msg)
    return base64.b64encode(bytes(tx)).decode()


async def verify_release_on_chain(tx_signature: str, escrow_pda: str, organizer_wallet: str) -> bool:
    """Confirm a release_prize transaction landed on-chain with the expected accounts."""
    resp = await _rpc_post(
        "getTransaction",
        [tx_signature, {"encoding": "jsonParsed", "commitment": "confirmed", "maxSupportedTransactionVersion": 0}],
    )
    tx = resp.get("result")
    if not tx:
        return False
    if tx.get("meta", {}).get("err") is not None:
        return False

    message = tx.get("transaction", {}).get("message", {})
    account_keys = message.get("accountKeys", [])

    all_pubkeys: set = set()
    signer_pubkeys: set = set()
    for acc in account_keys:
        if isinstance(acc, dict):
            pk = acc.get("pubkey", "")
            all_pubkeys.add(pk)
            if acc.get("signer"):
                signer_pubkeys.add(pk)
        else:
            all_pubkeys.add(str(acc))

    if organizer_wallet not in signer_pubkeys:
        return False
    if escrow_pda not in all_pubkeys:
        return False
    if ESCROW_PROGRAM not in all_pubkeys:
        return False

    instructions = message.get("instructions", [])
    return any(
        isinstance(ix, dict) and ix.get("programId") == ESCROW_PROGRAM
        for ix in instructions
    )


async def build_register_project_transaction(
    team_lead_wallet: str,
    escrow_pda: str,
    project_id_str: str,
) -> tuple[str, str]:
    team_lead = Pubkey.from_string(team_lead_wallet)
    escrow = Pubkey.from_string(escrow_pda)
    escrow_program = Pubkey.from_string(ESCROW_PROGRAM)
    project_id_bytes = _uuid.UUID(project_id_str).bytes
    project_record, _ = Pubkey.find_program_address(
        [b"project", bytes(escrow), project_id_bytes],
        escrow_program,
    )

    register_ix = Instruction(
        program_id=escrow_program,
        accounts=[
            AccountMeta(pubkey=team_lead, is_signer=True, is_writable=True),
            AccountMeta(pubkey=escrow, is_signer=False, is_writable=True),
            AccountMeta(pubkey=project_record, is_signer=False, is_writable=True),
            AccountMeta(pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
        ],
        data=_anchor_discriminator("register_project") + project_id_bytes,
    )

    instructions = []

    fee = _settings.registration_fee_usdc
    if fee > 0 and _settings.builder_pass_treasury:
        usdc_mint_pk = Pubkey.from_string(ESCROW_USDC_MINT)
        treasury_pk = Pubkey.from_string(_settings.builder_pass_treasury)
        team_lead_ata = _find_ata(team_lead, usdc_mint_pk)
        treasury_ata = _find_ata(treasury_pk, usdc_mint_pk)

        # Idempotent create treasury ATA (no-op if already exists)
        instructions.append(Instruction(
            program_id=ASSOCIATED_TOKEN_PROGRAM,
            accounts=[
                AccountMeta(pubkey=team_lead, is_signer=True, is_writable=True),
                AccountMeta(pubkey=treasury_ata, is_signer=False, is_writable=True),
                AccountMeta(pubkey=treasury_pk, is_signer=False, is_writable=False),
                AccountMeta(pubkey=usdc_mint_pk, is_signer=False, is_writable=False),
                AccountMeta(pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
                AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
            ],
            data=bytes([1]),
        ))

        # USDC transfer: team_lead → treasury
        instructions.append(Instruction(
            program_id=TOKEN_PROGRAM_ID,
            accounts=[
                AccountMeta(pubkey=team_lead_ata, is_signer=False, is_writable=True),
                AccountMeta(pubkey=treasury_ata, is_signer=False, is_writable=True),
                AccountMeta(pubkey=team_lead, is_signer=True, is_writable=False),
            ],
            data=bytes([3]) + struct.pack("<Q", fee),
        ))

    instructions.append(register_ix)

    bh_resp = await _rpc_post("getLatestBlockhash", [{"commitment": "confirmed"}])
    recent_blockhash = Hash.from_string(bh_resp["result"]["value"]["blockhash"])
    msg = Message.new_with_blockhash(instructions, team_lead, recent_blockhash)
    tx = Transaction.new_unsigned(msg)
    return base64.b64encode(bytes(tx)).decode(), str(project_record)


def derive_project_record_pda(escrow_pda: str, project_id_str: str) -> str:
    escrow = Pubkey.from_string(escrow_pda)
    escrow_program = Pubkey.from_string(ESCROW_PROGRAM)
    project_id_bytes = _uuid.UUID(project_id_str).bytes
    project_record, _ = Pubkey.find_program_address(
        [b"project", bytes(escrow), project_id_bytes],
        escrow_program,
    )
    return str(project_record)


async def build_claim_prize_transaction(
    winner_wallet: str,
    hackathon_id_str: str,
    escrow_pda: str,
    project_id_str: str,
    prize_usdc: int,
) -> tuple[str, datetime]:
    winner = Pubkey.from_string(winner_wallet)
    escrow = Pubkey.from_string(escrow_pda)
    escrow_program = Pubkey.from_string(ESCROW_PROGRAM)
    usdc_mint = Pubkey.from_string(ESCROW_USDC_MINT)
    platform_admin_kp = _escrow_platform_admin_keypair()
    hackathon_id_bytes = _uuid.UUID(hackathon_id_str).bytes
    project_id_bytes = _uuid.UUID(project_id_str).bytes
    nonce = _uuid.uuid4().bytes
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    expires_ts = int(expires_at.timestamp())
    project_record, _ = Pubkey.find_program_address(
        [b"project", bytes(escrow), project_id_bytes],
        escrow_program,
    )
    vault = _find_ata(escrow, usdc_mint)
    winner_usdc_ata = _find_ata(winner, usdc_mint)
    message = _claim_message(
        escrow_program,
        escrow,
        hackathon_id_bytes,
        project_id_bytes,
        winner,
        prize_usdc,
        expires_ts,
        nonce,
    )
    signature = bytes(platform_admin_kp.sign_message(message))
    ed25519_ix = _ed25519_verify_instruction(platform_admin_kp.pubkey(), signature, message)
    create_winner_ata_ix = Instruction(
        program_id=ASSOCIATED_TOKEN_PROGRAM,
        accounts=[
            AccountMeta(pubkey=winner, is_signer=True, is_writable=True),
            AccountMeta(pubkey=winner_usdc_ata, is_signer=False, is_writable=True),
            AccountMeta(pubkey=winner, is_signer=False, is_writable=False),
            AccountMeta(pubkey=usdc_mint, is_signer=False, is_writable=False),
            AccountMeta(pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        ],
        data=bytes([1]),
    )
    claim_ix = Instruction(
        program_id=escrow_program,
        accounts=[
            AccountMeta(pubkey=winner, is_signer=True, is_writable=True),
            AccountMeta(pubkey=usdc_mint, is_signer=False, is_writable=False),
            AccountMeta(pubkey=escrow, is_signer=False, is_writable=True),
            AccountMeta(pubkey=project_record, is_signer=False, is_writable=False),
            AccountMeta(pubkey=vault, is_signer=False, is_writable=True),
            AccountMeta(pubkey=winner_usdc_ata, is_signer=False, is_writable=True),
            AccountMeta(pubkey=INSTRUCTIONS_SYSVAR_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        ],
        data=(
            _anchor_discriminator("claim_prize")
            + hackathon_id_bytes
            + project_id_bytes
            + struct.pack("<Q", prize_usdc)
            + struct.pack("<q", expires_ts)
            + nonce
        ),
    )
    bh_resp = await _rpc_post("getLatestBlockhash", [{"commitment": "confirmed"}])
    recent_blockhash = Hash.from_string(bh_resp["result"]["value"]["blockhash"])
    msg = Message.new_with_blockhash([create_winner_ata_ix, ed25519_ix, claim_ix], winner, recent_blockhash)
    tx = Transaction.new_unsigned(msg)
    return base64.b64encode(bytes(tx)).decode(), expires_at


async def build_refund_transaction(
    organizer_wallet: str,
    hackathon_id_str: str,
    escrow_pda: str,
) -> str:
    organizer = Pubkey.from_string(organizer_wallet)
    escrow = Pubkey.from_string(escrow_pda)
    usdc_mint = Pubkey.from_string(ESCROW_USDC_MINT)
    escrow_program = Pubkey.from_string(ESCROW_PROGRAM)
    hackathon_id_bytes = _uuid.UUID(hackathon_id_str).bytes
    vault = _find_ata(escrow, usdc_mint)
    organizer_usdc_ata = _find_ata(organizer, usdc_mint)
    instruction = Instruction(
        program_id=escrow_program,
        accounts=[
            AccountMeta(pubkey=organizer, is_signer=True, is_writable=True),
            AccountMeta(pubkey=usdc_mint, is_signer=False, is_writable=False),
            AccountMeta(pubkey=escrow, is_signer=False, is_writable=True),
            AccountMeta(pubkey=vault, is_signer=False, is_writable=True),
            AccountMeta(pubkey=organizer_usdc_ata, is_signer=False, is_writable=True),
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        ],
        data=_anchor_discriminator("refund_escrow") + hackathon_id_bytes,
    )
    bh_resp = await _rpc_post("getLatestBlockhash", [{"commitment": "confirmed"}])
    recent_blockhash = Hash.from_string(bh_resp["result"]["value"]["blockhash"])
    msg = Message.new_with_blockhash([instruction], organizer, recent_blockhash)
    tx = Transaction.new_unsigned(msg)
    return base64.b64encode(bytes(tx)).decode()


async def verify_program_transaction_on_chain(
    tx_signature: str,
    expected_signer: str,
    required_accounts: list[str],
    instruction_name: str,
    commitment: str = "confirmed",
) -> bool:
    tx = await fetch_confirmed_transaction(tx_signature, rpc_url=RPC_URL, commitment=commitment)
    if expected_signer not in _tx_signers(tx):
        return False
    return _has_program_instruction(
        tx,
        ESCROW_PROGRAM,
        _anchor_discriminator(instruction_name),
        required_accounts,
    )


async def verify_escrow_account_on_chain(
    hackathon_id_str: str,
    escrow_pubkey: str,
    organizer_wallet: str,
    prize_usdc: int,
    voting_start_ts: int,
    voting_end_ts: int,
) -> bool:
    escrow_program = Pubkey.from_string(ESCROW_PROGRAM)
    expected_pda, _ = Pubkey.find_program_address(
        [b"hackathon_escrow", _uuid.UUID(hackathon_id_str).bytes],
        escrow_program,
    )
    if str(expected_pda) != escrow_pubkey:
        return False

    resp = await _rpc_post(
        "getAccountInfo",
        [escrow_pubkey, {"encoding": "base64", "commitment": "confirmed"}],
        rpc_url=MAINNET_RPC_URL,
    )
    value = (resp.get("result") or {}).get("value")
    if not value or value.get("owner") != ESCROW_PROGRAM:
        return False

    data = base64.b64decode(value["data"][0])
    # HackathonEscrow binary layout (154 bytes total):
    # 8 disc | 32 organizer | 32 usdc_mint | 32 platform_admin | 16 hackathon_id
    # | 8 prize_usdc | 8 voting_start | 8 voting_end | 4 project_count
    # | 4 submitted_project_count | 1 status | 1 bump
    if len(data) < 154:
        return False

    pos = 8
    organizer = str(Pubkey.from_bytes(data[pos:pos + 32])); pos += 32
    usdc_mint = str(Pubkey.from_bytes(data[pos:pos + 32])); pos += 32
    platform_admin = str(Pubkey.from_bytes(data[pos:pos + 32])); pos += 32
    hackathon_id = data[pos:pos + 16]; pos += 16
    prize = struct.unpack_from("<Q", data, pos)[0]; pos += 8
    voting_start = struct.unpack_from("<q", data, pos)[0]; pos += 8
    voting_end = struct.unpack_from("<q", data, pos)[0]; pos += 8
    project_count = struct.unpack_from("<I", data, pos)[0]; pos += 4
    submitted_project_count = struct.unpack_from("<I", data, pos)[0]; pos += 4
    status = data[pos]

    expected_admin = str(_escrow_platform_admin_keypair().pubkey())

    return (
        organizer == organizer_wallet
        and usdc_mint == ESCROW_USDC_MINT
        and platform_admin == expected_admin
        and hackathon_id == _uuid.UUID(hackathon_id_str).bytes
        and prize == prize_usdc
        and voting_start == voting_start_ts
        and voting_end == voting_end_ts
        and project_count == 0
        and submitted_project_count == 0
        and status == 0
    )


async def build_mark_submitted_transaction(
    user_wallet: str,
    hackathon_id_str: str,
    escrow_pda: str,
    project_id_str: str,
) -> str:
    """
    Build a mark_submitted transaction for the user to sign as fee payer.
    Platform admin co-signs as authority only — no SOL needed in the backend wallet.
    Returns a base64-encoded partially-signed transaction.
    """
    platform_admin_kp = _escrow_platform_admin_keypair()
    platform_admin = platform_admin_kp.pubkey()
    user = Pubkey.from_string(user_wallet)
    escrow = Pubkey.from_string(escrow_pda)
    escrow_program = Pubkey.from_string(ESCROW_PROGRAM)
    hackathon_id_bytes = _uuid.UUID(hackathon_id_str).bytes
    project_id_bytes = _uuid.UUID(project_id_str).bytes

    project_record, _ = Pubkey.find_program_address(
        [b"project", bytes(escrow), project_id_bytes],
        escrow_program,
    )

    instruction = Instruction(
        program_id=escrow_program,
        accounts=[
            AccountMeta(pubkey=platform_admin, is_signer=True, is_writable=False),
            AccountMeta(pubkey=escrow, is_signer=False, is_writable=True),
            AccountMeta(pubkey=project_record, is_signer=False, is_writable=True),
        ],
        data=_anchor_discriminator("mark_submitted") + hackathon_id_bytes + project_id_bytes,
    )

    bh_resp = await _rpc_post("getLatestBlockhash", [{"commitment": "confirmed"}])
    recent_blockhash = Hash.from_string(bh_resp["result"]["value"]["blockhash"])
    msg = Message.new_with_blockhash([instruction], user, recent_blockhash)
    tx = Transaction.new_unsigned(msg)
    tx.partial_sign([platform_admin_kp], recent_blockhash)
    return base64.b64encode(bytes(tx)).decode()
