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
    skr_per_multiplier_step: int = 100

    # Builder Pass NFT
    builder_pass_collection_mint: str = ""
    builder_pass_treasury: str = ""
    builder_pass_metadata_uri: str = ""
    builder_pass_authority_keypair: str = "[]"  # JSON array of keypair bytes
    builder_pass_price_usdc: int = 10_000_000   # $10 USDC (6 decimals); set to 0 to disable payment
    builder_pass_sol_fee_lamports: int = 25_000_000  # 0.025 SOL sent to authority to cover mint costs

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
