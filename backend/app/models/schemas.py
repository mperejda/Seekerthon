import re
from pydantic import BaseModel, UUID4, field_validator
from typing import Optional, List, Literal
from datetime import datetime
from enum import Enum


class HackathonStatus(str, Enum):
    draft = "draft"
    open = "open"
    voting = "voting"
    verifying = "verifying"
    completed = "completed"


class ProjectStatus(str, Enum):
    registered = "registered"          # on-chain PDA exists, details not yet filled in
    pending_registration = "pending_registration"  # legacy — no longer issued
    submitted = "submitted"
    approved = "approved"
    winner = "winner"
    rejected = "rejected"


# ── Users ──────────────────────────────────────────────────────────────────

class UserBase(BaseModel):
    wallet_address: str


class UserCreate(UserBase):
    signature: str  # signed challenge from Seeker wallet
    challenge: str


class UserResponse(UserBase):
    id: UUID4
    skr_balance: int = 0
    skr_staked: int = 0
    vote_multiplier: float = 1.0
    is_seeker_verified: bool = False
    has_builder_pass: bool = False
    skr_id: Optional[str] = None
    votes_cast: int = 0
    hackathons_voted: int = 0
    support_nfts_minted: int = 0
    skr_staked_rank: Optional[int] = None
    skr_staked_percentile: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class MintPrepareResponse(BaseModel):
    transaction_b64: str
    mint_address: str


class MintConfirmRequest(BaseModel):
    tx_signature: str
    mint_address: str


class MintConfirmResponse(BaseModel):
    success: bool
    tx_signature: str


class WalletChallenge(BaseModel):
    challenge: str
    expires_at: datetime


class AuthToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class ActivityVotedProject(BaseModel):
    project_id: str
    project_name: str
    hackathon_title: str


class ActivitySupportNft(BaseModel):
    project_id: str
    project_name: str
    hackathon_title: str
    asset_id: Optional[str] = None


class UserActivityResponse(BaseModel):
    voted_projects: List[ActivityVotedProject]
    support_nfts: List[ActivitySupportNft]


# ── Hackathons ──────────────────────────────────────────────────────────────

_SOLANA_PUBKEY_RE = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')


class HackathonCreate(BaseModel):
    title: str
    description: str
    prize_pool_usdc: int
    voting_start: datetime
    voting_end: datetime
    max_projects: int = 100
    signing_flow: Literal["backend_presigned", "wallet_first"] = "backend_presigned"


class HackathonUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[HackathonStatus] = None


class EscrowSetRequest(BaseModel):
    escrow_pubkey: str
    onchain_pda: str

    @field_validator("escrow_pubkey", "onchain_pda")
    @classmethod
    def validate_solana_pubkey(cls, v: str) -> str:
        if not _SOLANA_PUBKEY_RE.match(v):
            raise ValueError("Invalid Solana public key format")
        return v


class EscrowFinalizeRequest(BaseModel):
    signed_tx_b64: str
    escrow_pubkey: str

    @field_validator("escrow_pubkey")
    @classmethod
    def validate_solana_pubkey(cls, v: str) -> str:
        if not _SOLANA_PUBKEY_RE.match(v):
            raise ValueError("Invalid Solana public key format")
        return v


class HackathonResponse(BaseModel):
    id: UUID4
    organizer_id: UUID4
    title: str
    description: str
    prize_pool_usdc: int
    escrow_pubkey: Optional[str] = None
    onchain_pda: Optional[str] = None
    status: HackathonStatus
    voting_start: datetime
    voting_end: datetime
    max_projects: int
    project_count: int = 0
    registration_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


class HackathonCreateResponse(BaseModel):
    hackathon: HackathonResponse
    transaction_b64: str
    escrow_pda: str


class EscrowFinalizeResponse(BaseModel):
    hackathon: HackathonResponse
    tx_signature: str


# ── Registrations ─────────────────────────────────────────────────────────────

class HackathonRegistrationResponse(BaseModel):
    id: UUID4
    hackathon_id: UUID4
    user_id: UUID4
    wallet_address: str
    project_id: Optional[UUID4] = None
    registered_at: datetime

    class Config:
        from_attributes = True


class RegistrationPrepareResponse(BaseModel):
    """Returned by GET /hackathons/{id}/register-tx. transaction_b64 is None for no-escrow hackathons."""
    transaction_b64: Optional[str] = None
    project_id: str
    project_record_pda: Optional[str] = None


class RegistrationConfirmRequest(BaseModel):
    tx_signature: Optional[str] = None   # required when hackathon has an escrow
    project_id: str                       # must match what was returned by register-tx


class RegistrationStatusResponse(BaseModel):
    is_registered: bool
    registration: Optional[HackathonRegistrationResponse] = None
    spots_taken: int
    spots_remaining: int
    spots_total: int


# ── Project submission ────────────────────────────────────────────────────────

class ProjectSubmit(BaseModel):
    name: str
    description: str
    demo_url: Optional[str] = None
    repo_url: Optional[str] = None
    tech_stack: List[str] = []


# ── Projects ──────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    hackathon_id: UUID4
    name: str
    description: str
    demo_url: Optional[str] = None
    repo_url: Optional[str] = None
    tech_stack: List[str] = []


class ProjectResponse(BaseModel):
    id: UUID4
    hackathon_id: UUID4
    team_lead_id: UUID4
    name: str
    description: str
    demo_url: Optional[str] = None
    repo_url: Optional[str] = None
    tech_stack: List[str] = []
    storage_asset_ids: List[str] = []
    video_url: Optional[str] = None
    onchain_pda: Optional[str] = None
    status: ProjectStatus
    vote_count: float = 0.0
    created_at: datetime

    class Config:
        from_attributes = True


class SubmitTxResponse(BaseModel):
    transaction_b64: Optional[str] = None
    project: ProjectResponse


class SubmitConfirmRequest(BaseModel):
    tx_signature: str


# ── Assets ─────────────────────────────────────────────────────────────────

class AssetUploadUrlRequest(BaseModel):
    filename: str
    content_type: str


class AssetUploadUrlResponse(BaseModel):
    upload_url: str
    public_url: str
    key: str


class AssetConfirmRequest(BaseModel):
    key: str


class AssetConfirmResponse(BaseModel):
    public_url: str


# ── Votes ──────────────────────────────────────────────────────────────────

class VotePrepareRequest(BaseModel):
    project_id: UUID4


class VotePrepareResponse(BaseModel):
    vote_message: str           # structured message for the wallet to sign
    vote_weight: float
    voter_skr_staked: int
    expires_at: datetime


class VoteConfirmRequest(BaseModel):
    project_id: UUID4
    vote_message: str           # the original message that was signed
    tx_signature: str           # base58 ed25519 signature from the wallet


class VoteResponse(BaseModel):
    id: UUID4
    voter_id: UUID4
    project_id: UUID4
    weight: float
    tx_signature: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── Leaderboard ──────────────────────────────────────────────────────────────

class LeaderboardEntry(BaseModel):
    rank: int
    project: ProjectResponse
    total_votes: float
    unique_voters: int


# ── Prize release ─────────────────────────────────────────────────────────────

class ReleaseTxResponse(BaseModel):
    transaction_b64: str
    winner_wallet: str
    prize_lamports: int


class VerifyReleaseRequest(BaseModel):
    tx_signature: Optional[str] = None


class RegistrationTxResponse(BaseModel):
    transaction_b64: str
    project_record_pda: str


class ClaimTxResponse(BaseModel):
    transaction_b64: str
    winner_wallet: str
    prize_lamports: int
    expires_at: datetime


# ── Support NFT ───────────────────────────────────────────────────────────────

class SupportNftPrepareRequest(BaseModel):
    project_id: UUID4


class SupportNftPrepareResponse(BaseModel):
    transaction_b64: str
    amount_display: str
    treasury_amount_display: str
    builder_amount_display: str
    project_name: str
    project_id: str


class SupportNftClaimRequest(BaseModel):
    signed_tx_b64: str
    project_id: UUID4


class SupportNftClaimResponse(BaseModel):
    success: bool
    tx_signature: str


class SupportNftMineResponse(BaseModel):
    project_ids: List[str]
