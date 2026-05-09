"""
Solana service: reads on-chain state and builds unsigned vote transactions.
Uses solders for low-level Solana types and anchorpy for program interaction.
"""
import asyncio
import base64
import json
import logging
import math
import struct
import uuid as _uuid
from typing import Tuple

from solders.keypair import Keypair as SoldersKeypair
from solders.pubkey import Pubkey
from solders.signature import Signature as SoldersSignature
from solders.transaction import Transaction
from solders.message import Message
from solders.instruction import Instruction, AccountMeta
from solders.hash import Hash
import httpx

from app.config import get_settings

_log = logging.getLogger(__name__)
_settings = get_settings()

RPC_URL = _settings.solana_rpc_url
MAINNET_RPC_URL = _settings.solana_mainnet_rpc_url
SKR_MINT = _settings.skr_token_mint
GENESIS_COLLECTION = _settings.seeker_genesis_collection
VOTING_PROGRAM = _settings.voting_program_id
ESCROW_PROGRAM = _settings.escrow_program_id
USDC_MINT = _settings.usdc_mint
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
    resp = await _rpc_post(
        "getTokenAccountsByOwner",
        [wallet_address, {"mint": SKR_MINT}, {"encoding": "jsonParsed", "commitment": "confirmed"}],
        rpc_url=MAINNET_RPC_URL,
    )
    balance_raw = 0
    decimals = 6  # SKR always has 6 decimals; used as fallback if no accounts found
    for acct in (resp.get("result", {}).get("value") or []):
        info = acct.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
        ta = info.get("tokenAmount", {})
        balance_raw += int(ta.get("amount", 0))
        decimals = int(ta.get("decimals", decimals))

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
    """
    raw = 1.0 + math.log2(1.0 + skr_staked / SKR_PER_STEP)
    base = round(min(raw, MAX_MULTIPLIER), 4)
    if has_builder_pass:
        return round(min(base * 5.0, MAX_MULTIPLIER * 5.0), 4)
    return base


def _borsh_str(s: str) -> bytes:
    enc = s.encode("utf-8")
    return struct.pack("<I", len(enc)) + enc


async def build_builder_pass_mint_transaction(buyer_wallet: str) -> tuple[str, str]:
    """
    Build a partially-signed NFT mint transaction for the Alpine Labs Builder Pass.
    Instructions: createAccount + initializeMint + createATA + mintTo +
                  createMetadataV3 + createMasterEditionV3 + USDC transfer ($10).
    Backend signs with authority + mint keypairs; buyer adds their signature via MWA.
    Returns (base64_tx, mint_address).
    """
    settings = _settings

    authority_kp = SoldersKeypair.from_bytes(bytes(json.loads(settings.builder_pass_authority_keypair)))
    authority_pk = authority_kp.pubkey()

    mint_kp = SoldersKeypair()
    mint_pk = mint_kp.pubkey()

    buyer_pk = Pubkey.from_string(buyer_wallet)
    usdc_mint_pk = Pubkey.from_string(USDC_MINT)
    collection_mint_pk = Pubkey.from_string(settings.builder_pass_collection_mint)
    treasury_pk = Pubkey.from_string(settings.builder_pass_treasury)

    buyer_nft_ata = _find_ata(buyer_pk, mint_pk)
    buyer_usdc_ata = _find_ata(buyer_pk, usdc_mint_pk)
    treasury_usdc_ata = _find_ata(treasury_pk, usdc_mint_pk)

    metadata_pda, _ = Pubkey.find_program_address(
        [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(mint_pk)],
        METADATA_PROGRAM_ID,
    )
    edition_pda, _ = Pubkey.find_program_address(
        [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(mint_pk), b"edition"],
        METADATA_PROGRAM_ID,
    )

    SYSVAR_RENT = Pubkey.from_string("SysvarRent111111111111111111111111111111111")

    # Rent exemption for the 82-byte mint account
    rent_resp = await _rpc_post("getMinimumBalanceForRentExemption", [82], rpc_url=MAINNET_RPC_URL)
    mint_rent = rent_resp["result"]

    # 1. CreateAccount (system program) — allocate mint account
    ix_create_account = Instruction(
        program_id=SYSTEM_PROGRAM_ID,
        accounts=[
            AccountMeta(pubkey=buyer_pk, is_signer=True, is_writable=True),
            AccountMeta(pubkey=mint_pk, is_signer=True, is_writable=True),
        ],
        data=(
            struct.pack("<I", 0)             # SystemInstruction::CreateAccount
            + struct.pack("<Q", mint_rent)   # lamports
            + struct.pack("<Q", 82)          # space (mint state)
            + bytes(TOKEN_PROGRAM_ID)        # owner
        ),
    )

    # 2. InitializeMint — 0 decimals, authority = builder pass authority
    ix_init_mint = Instruction(
        program_id=TOKEN_PROGRAM_ID,
        accounts=[
            AccountMeta(pubkey=mint_pk, is_signer=False, is_writable=True),
            AccountMeta(pubkey=SYSVAR_RENT, is_signer=False, is_writable=False),
        ],
        data=(
            bytes([0])              # InitializeMint
            + bytes([0])            # decimals
            + bytes(authority_pk)   # mint_authority
            + struct.pack("<I", 0)  # freeze_authority = COption::None
        ),
    )

    # 3. Create ATA for buyer (idempotent)
    ix_create_ata = Instruction(
        program_id=ASSOCIATED_TOKEN_PROGRAM,
        accounts=[
            AccountMeta(pubkey=buyer_pk, is_signer=True, is_writable=True),
            AccountMeta(pubkey=buyer_nft_ata, is_signer=False, is_writable=True),
            AccountMeta(pubkey=buyer_pk, is_signer=False, is_writable=False),
            AccountMeta(pubkey=mint_pk, is_signer=False, is_writable=False),
            AccountMeta(pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        ],
        data=bytes([1]),  # CreateIdempotent
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

    # 5. CreateMetadataAccountV3
    ix_create_metadata = Instruction(
        program_id=METADATA_PROGRAM_ID,
        accounts=[
            AccountMeta(pubkey=metadata_pda, is_signer=False, is_writable=True),
            AccountMeta(pubkey=mint_pk, is_signer=False, is_writable=False),
            AccountMeta(pubkey=authority_pk, is_signer=True, is_writable=False),   # mint authority
            AccountMeta(pubkey=buyer_pk, is_signer=True, is_writable=True),         # payer
            AccountMeta(pubkey=authority_pk, is_signer=False, is_writable=False),  # update authority
            AccountMeta(pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=SYSVAR_RENT, is_signer=False, is_writable=False),
        ],
        data=(
            bytes([33])
            + _borsh_str("Alpine Labs Builder Pass")
            + _borsh_str("ALBP")
            + _borsh_str(settings.builder_pass_metadata_uri)
            + struct.pack("<H", 0)             # seller_fee_basis_points
            + bytes([0])                       # creators: None
            + bytes([1])                       # collection: Some
            + bytes([0])                       # verified = false
            + bytes(collection_mint_pk)        # collection key
            + bytes([0])                       # uses: None
            + bytes([1])                       # is_mutable = true
            + bytes([0])                       # collection_details: None
        ),
    )

    # 6. CreateMasterEditionV3 — max_supply = Some(0) for 1/1
    ix_create_edition = Instruction(
        program_id=METADATA_PROGRAM_ID,
        accounts=[
            AccountMeta(pubkey=edition_pda, is_signer=False, is_writable=True),
            AccountMeta(pubkey=mint_pk, is_signer=False, is_writable=True),
            AccountMeta(pubkey=authority_pk, is_signer=True, is_writable=False),   # update authority
            AccountMeta(pubkey=authority_pk, is_signer=True, is_writable=False),   # mint authority
            AccountMeta(pubkey=buyer_pk, is_signer=True, is_writable=True),         # payer
            AccountMeta(pubkey=metadata_pda, is_signer=False, is_writable=False),
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=SYSVAR_RENT, is_signer=False, is_writable=False),
        ],
        data=bytes([17]) + bytes([1]) + struct.pack("<Q", 0),  # max_supply = Some(0)
    )

    # 7. SPL Token Transfer — $10 USDC from buyer to treasury
    ix_usdc_transfer = Instruction(
        program_id=TOKEN_PROGRAM_ID,
        accounts=[
            AccountMeta(pubkey=buyer_usdc_ata, is_signer=False, is_writable=True),
            AccountMeta(pubkey=treasury_usdc_ata, is_signer=False, is_writable=True),
            AccountMeta(pubkey=buyer_pk, is_signer=True, is_writable=False),
        ],
        data=bytes([3]) + struct.pack("<Q", 10_000_000),  # 10 USDC (6 decimals)
    )

    bh_resp = await _rpc_post("getLatestBlockhash", [{"commitment": "confirmed"}], rpc_url=MAINNET_RPC_URL)
    recent_blockhash = Hash.from_string(bh_resp["result"]["value"]["blockhash"])

    instructions = [
        ix_create_account, ix_init_mint, ix_create_ata,
        ix_mint_to, ix_create_metadata, ix_create_edition, ix_usdc_transfer,
    ]
    msg = Message.new_with_blockhash(instructions, buyer_pk, recent_blockhash)

    # Partially sign with authority + mint keypairs; buyer slot stays zeroed
    msg_bytes = bytes(msg)
    num_signers = msg.header.num_required_signatures
    sigs: list[SoldersSignature] = []
    for i in range(num_signers):
        pk = msg.account_keys[i]
        if pk == authority_pk:
            sigs.append(authority_kp.sign_message(msg_bytes))
        elif pk == mint_pk:
            sigs.append(mint_kp.sign_message(msg_bytes))
        else:
            sigs.append(SoldersSignature.default())

    tx = Transaction.populate(msg, sigs)
    return base64.b64encode(bytes(tx)).decode(), str(mint_pk)


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

    if not project_pda:
        # Memo path: mainnet, always simulates cleanly
        instruction = Instruction(
            program_id=MEMO_PROGRAM_ID,
            accounts=[AccountMeta(pubkey=voter, is_signer=True, is_writable=False)],
            data=f"seeker-vote:bps={vote_weight_bps}".encode(),
        )
        bh_resp = await _rpc_post("getLatestBlockhash", [{"commitment": "confirmed"}], rpc_url=MAINNET_RPC_URL)
    else:
        # Full voting-program path: devnet
        project = Pubkey.from_string(project_pda)
        voting_program = Pubkey.from_string(VOTING_PROGRAM)
        vote_record_pda, _ = Pubkey.find_program_address(
            [b"vote", bytes(voter), bytes(project)], voting_program
        )
        discriminator = bytes([0x14, 0xD4, 0x0F, 0xBD, 0x45, 0xB4, 0x45, 0x97])
        instruction = Instruction(
            program_id=voting_program,
            accounts=[
                AccountMeta(pubkey=voter, is_signer=True, is_writable=True),
                AccountMeta(pubkey=project, is_signer=False, is_writable=True),
                AccountMeta(pubkey=vote_record_pda, is_signer=False, is_writable=True),
                AccountMeta(pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
            ],
            data=discriminator + struct.pack("<H", vote_weight_bps),
        )
        bh_resp = await _rpc_post("getLatestBlockhash", [{"commitment": "confirmed"}])

    blockhash_str = bh_resp["result"]["value"]["blockhash"]
    recent_blockhash = Hash.from_string(blockhash_str)
    msg = Message.new_with_blockhash([instruction], voter, recent_blockhash)
    tx = Transaction.new_unsigned(msg)
    return base64.b64encode(bytes(tx)).decode()


async def verify_transaction_on_chain(tx_signature: str, project_pda: str | None, voter_wallet: str) -> bool:
    """
    Confirm a vote transaction landed on-chain and the voter signed it.
    Memo transactions (no project_pda) are verified on mainnet.
    Voting-program transactions are verified on devnet.
    """
    rpc = MAINNET_RPC_URL if not project_pda else RPC_URL
    resp = await _rpc_post(
        "getTransaction",
        [tx_signature, {"encoding": "jsonParsed", "commitment": "confirmed", "maxSupportedTransactionVersion": 0}],
        rpc_url=rpc,
    )
    tx_data = resp.get("result")
    if not tx_data:
        return False
    if tx_data.get("meta", {}).get("err") is not None:
        return False

    message = tx_data.get("transaction", {}).get("message", {})
    signer_pubkeys: set = set()
    all_pubkeys: set = set()
    for acc in message.get("accountKeys", []):
        if isinstance(acc, dict):
            pk = acc.get("pubkey", "")
            all_pubkeys.add(pk)
            if acc.get("signer"):
                signer_pubkeys.add(pk)
        else:
            all_pubkeys.add(str(acc))

    if voter_wallet not in signer_pubkeys:
        return False
    if not project_pda:
        return True  # memo tx: voter signed + tx succeeded is sufficient

    if project_pda not in all_pubkeys:
        return False
    if VOTING_PROGRAM not in all_pubkeys:
        return False
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
