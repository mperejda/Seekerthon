from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List


class Settings(BaseSettings):
    supabase_url: str
    supabase_key: str
    supabase_service_role_key: str
    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"
    solana_rpc_url_devnet: str = "https://api.devnet.solana.com"
    solana_mainnet_rpc_url: str = "https://api.mainnet-beta.solana.com"
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7

    # Comma-separated list of allowed CORS origins (e.g. http://localhost:3000)
    cors_origins: List[str] = ["http://localhost:3000"]

    # Solana program IDs — must be set in .env after on-chain deployment
    escrow_program_id: str
    escrow_platform_admin_keypair: str = "[]"  # JSON array of keypair bytes; co-signs escrow create and winner certs

    # Seeker Genesis NFT collection address and SKR token mint — must be set in .env
    seeker_genesis_collection: str
    skr_token_mint: str

    # USDC mint used by the Builder Pass purchase flow (mainnet)
    # Mainnet: EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v
    usdc_mint: str

    # USDC mint used by the escrow program (devnet for testing, mainnet for production)
    # Devnet:  4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU
    # Mainnet: EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v
    escrow_usdc_mint: str = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"

    # Vote weight config
    max_vote_multiplier: float = 5.0
    skr_per_multiplier_step: int = 4167

    # Cloudflare R2 storage (for project demo videos)
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = ""
    r2_public_url: str = ""

    # Builder Pass NFT
    builder_pass_collection_mint: str = ""
    builder_pass_treasury: str = ""
    builder_pass_metadata_uri: str = ""
    builder_pass_authority_keypair: str = "[]"  # JSON array of keypair bytes
    builder_pass_price_usdc: int = 50_000_000   # $50 USDC (6 decimals); set to 0 to disable payment
    builder_pass_sol_fee_lamports: int = 0  # Deprecated; backend pays Builder Pass mint rent/fees
    builder_pass_min_mint_balance_lamports: int = 30_000_000  # 0.03 SOL; conservative one-mint threshold
    sol_usd_price_url: str = "https://api.coingecko.com/api/v3/simple/price"

    # Registration fee (USDC, 6 decimals) collected at hackathon sign-up; goes to builder_pass_treasury
    registration_fee_usdc: int = 2_000_000  # $2.00 USDC; set to 0 to disable

    # Builder Support NFT (cNFT via Bubblegum)
    support_nft_price_usdc: int = 5_000_000       # $5.00 USDC (6 decimals)
    support_nft_treasury_bps: int = 500            # 5% to treasury (500 basis points)
    support_nft_tree_address: str = ""             # Bubblegum Merkle tree pubkey
    support_nft_collection_mint: str = ""          # Collection NFT mint pubkey
    support_nft_image_uri: str = ""                # Seekerthon logo URL for NFT image
    api_base_url: str = "https://app.seekerthon.com"  # Base URL for dynamic metadata URIs

    # AWS Rekognition — separate IAM credentials from Cloudflare R2
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"

    # Firebase Cloud Messaging — service account JSON as a single-line string
    firebase_service_account_json: str = ""

    # Cherry chat embed secret. Server-side only; never expose in Android/web clients.
    cherry_app_secret: str = ""

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
