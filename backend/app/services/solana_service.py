"""
Solana service: reads on-chain state and builds unsigned vote transactions.
Uses solders for low-level Solana types and anchorpy for program interaction.
"""
import base64
import logging
import math
import struct
import uuid as _uuid
from typing import Tuple

from solders.pubkey import Pubkey
from solders.transaction import Transaction
from solders.message import Message
from solders.instruction import Instruction, AccountMeta
from solders.hash import Hash
import httpx

from app.config import get_settings

_log = logging.getLogger(__name__)
_settings = get_settings()

RPC_URL = _settings.solana_rpc_url
MAINNET_RPC_URL = "https://api.mainnet-beta.solana.com"
SKR_MINT = _settings.skr_token_mint
GENESIS_COLLECTION = _settings.seeker_genesis_collection
VOTING_PROGRAM = _settings.voting_program_id
ESCROW_PROGRAM = _settings.escrow_program_id
USDC_MINT = _settings.usdc_mint
USDC_DECIMALS = 6
MAX_MULTIPLIER = _settings.max_vote_multiplier
SKR_PER_STEP = _settings.skr_per_multiplier_step

# SPL Token program
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
TOKEN_2022_PROGRAM_ID = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
METADATA_PROGRAM_ID = Pubkey.from_string("metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s")
ASSOCIATED_TOKEN_PROGRAM = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJe1bQ")
SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")


async def _rpc_post(method: str, params: list, rpc_url: str = RPC_URL) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
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
    Returns (skr_balance, skr_staked) for a wallet.
    skr_balance: raw token amount in the ATA
    skr_staked: amount locked in the staking vault PDA
    """
    wallet = Pubkey.from_string(wallet_address)
    mint = Pubkey.from_string(SKR_MINT)
    ata = _find_ata(wallet, mint)

    resp = await _rpc_post(
        "getTokenAccountBalance",
        [str(ata), {"commitment": "confirmed"}],
    )
    balance = 0
    if "result" in resp and resp["result"]["value"]:
        balance = int(resp["result"]["value"]["amount"])

    # Staking vault PDA: seeds = [b"stake", wallet, mint]
    staking_pda, _ = Pubkey.find_program_address(
        [b"stake", bytes(wallet), bytes(mint)],
        Pubkey.from_string(VOTING_PROGRAM),
    )
    stake_resp = await _rpc_post(
        "getAccountInfo",
        [str(staking_pda), {"encoding": "base64", "commitment": "confirmed"}],
    )
    staked = 0
    if stake_resp.get("result", {}).get("value"):
        data_b64 = stake_resp["result"]["value"]["data"][0]
        data = base64.b64decode(data_b64)
        # Layout: [discriminator(8)] [amount(u64)] [owner(32)] [locked_until(i64)]
        if len(data) >= 48:
            staked = struct.unpack_from("<Q", data, 8)[0]

    return balance, staked


def compute_vote_weight(skr_staked: int) -> float:
    """
    Weight formula: 1 + log2(1 + staked / SKR_PER_STEP)
    Capped at MAX_MULTIPLIER.
    Gives smooth curve: 0 staked=1.0x, 100=2.0x, 300=3.0x, 700=4.0x, 1500=5.0x
    """
    raw = 1.0 + math.log2(1.0 + skr_staked / SKR_PER_STEP)
    return round(min(raw, MAX_MULTIPLIER), 4)


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




async def build_vote_transaction(
    voter_wallet: str,
    project_pda: str,
    hackathon_pda: str,
    vote_weight_bps: int,  # weight * 10000 as u16 to avoid floats on-chain
) -> str:
    """
    Build an unsigned Solana transaction for casting a vote.
    Returns base64-encoded transaction for the Android app to sign.
    """
    voter = Pubkey.from_string(voter_wallet)
    project = Pubkey.from_string(project_pda)
    voting_program = Pubkey.from_string(VOTING_PROGRAM)

    # Vote record PDA: seeds = [b"vote", voter, project]
    vote_record_pda, _ = Pubkey.find_program_address(
        [b"vote", bytes(voter), bytes(project)],
        voting_program,
    )

    # sha256("global:cast_vote")[:8]
    discriminator = bytes([0x14, 0xD4, 0x0F, 0xBD, 0x45, 0xB4, 0x45, 0x97])

    ix_data = discriminator + struct.pack("<H", vote_weight_bps)

    instruction = Instruction(
        program_id=voting_program,
        accounts=[
            AccountMeta(pubkey=voter, is_signer=True, is_writable=True),
            AccountMeta(pubkey=project, is_signer=False, is_writable=True),
            AccountMeta(pubkey=vote_record_pda, is_signer=False, is_writable=True),
            AccountMeta(pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
        ],
        data=ix_data,
    )

    bh_resp = await _rpc_post("getLatestBlockhash", [{"commitment": "confirmed"}])
    blockhash_str = bh_resp["result"]["value"]["blockhash"]
    recent_blockhash = Hash.from_string(blockhash_str)

    msg = Message.new_with_blockhash([instruction], voter, recent_blockhash)
    tx = Transaction.new_unsigned(msg)

    return base64.b64encode(bytes(tx)).decode()


async def verify_transaction_on_chain(tx_signature: str, project_pda: str, voter_wallet: str) -> bool:
    """
    Confirm a vote transaction landed on-chain and matches expected accounts.
    Checks: tx succeeded, voter is a signer, project PDA is referenced,
    and at least one instruction targets the voting program.
    """
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

    if voter_wallet not in signer_pubkeys:
        return False
    if project_pda not in all_pubkeys:
        return False
    if VOTING_PROGRAM not in all_pubkeys:
        return False

    # At least one instruction must target the voting program
    instructions = message.get("instructions", [])
    return any(
        isinstance(ix, dict) and ix.get("programId") == VOTING_PROGRAM
        for ix in instructions
    )


async def build_create_escrow_transaction(
    organizer_wallet: str,
    hackathon_id_str: str,
    prize_usdc: int,
    voting_start_ts: int,
    voting_end_ts: int,
) -> tuple[str, str]:
    """
    Build an unsigned create_hackathon transaction for the escrow program.
    Returns (base64_tx, escrow_pda_str).
    Instruction: create_hackathon(hackathon_id: [u8;16], prize_usdc: u64, voting_start: i64, voting_end: i64)
    """
    organizer = Pubkey.from_string(organizer_wallet)
    usdc_mint_pk = Pubkey.from_string(USDC_MINT)
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

    # sha256("global:create_hackathon")[:8]
    discriminator = bytes([0xe4, 0x94, 0xee, 0xf6, 0x15, 0xdf, 0x2f, 0x45])

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

    bh_resp = await _rpc_post("getLatestBlockhash", [{"commitment": "confirmed"}])
    blockhash_str = bh_resp["result"]["value"]["blockhash"]
    recent_blockhash = Hash.from_string(blockhash_str)

    msg = Message.new_with_blockhash([instruction], organizer, recent_blockhash)
    tx = Transaction.new_unsigned(msg)
    tx_b64 = base64.b64encode(bytes(tx)).decode()

    # Simulate first to surface program errors before sending to the client
    sim_resp = await _rpc_post(
        "simulateTransaction",
        [tx_b64, {"encoding": "base64", "commitment": "confirmed", "replaceRecentBlockhash": True}],
    )
    sim_result = sim_resp.get("result", {}).get("value", {})
    if sim_result.get("err"):
        logs = sim_result.get("logs") or []
        raise ValueError(f"Simulation failed: {sim_result['err']} | logs: {logs}")

    return tx_b64, str(escrow_pda)


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
    usdc_mint = Pubkey.from_string(USDC_MINT)
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
