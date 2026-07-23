package com.alpinelabs.seekerthon.data.remote

import retrofit2.http.*

// ── DTOs ──────────────────────────────────────────────────────────────────

data class WalletChallengeDto(val challenge: String, val expires_at: String)
data class UserCreateDto(val wallet_address: String, val signature: String, val challenge: String)
data class AuthTokenDto(val access_token: String, val token_type: String, val user: UserDto)
data class UserDto(
    val id: String,
    val wallet_address: String,
    val skr_balance: Long,
    val skr_staked: Long,
    val vote_multiplier: Double,
    val is_seeker_verified: Boolean,
    val has_builder_pass: Boolean = false,
    val skr_id: String? = null,
    val hackathons_voted: Int = 0,
    val skr_staked_rank: Int? = null,
    val skr_staked_percentile: Int? = null,
    val created_at: String,
)

data class MintPrepareResponseDto(
    val transaction_b64: String,
    val mint_pubkey: String,
    val amount_raw: Long,
    val amount_display: String,
    val sol_fee_lamports: Long,
    val sol_fee_display: String,
)
data class MintClaimRequestDto(val signed_tx_b64: String, val mint_pubkey: String)
data class MintConfirmResponseDto(val success: Boolean, val tx_signature: String)
data class BuilderPassStatusDto(
    val available: Boolean,
    val authority_balance_lamports: Long,
    val min_required_lamports: Long,
    val message: String,
)

data class HackathonDto(
    val id: String,
    val organizer_id: String,
    val title: String,
    val description: String,
    val prize_pool_usdc: Long,
    val escrow_pubkey: String?,
    val status: String,
    val voting_start: String,
    val voting_end: String,
    val project_count: Int,
)

data class ProjectDto(
    val id: String,
    val hackathon_id: String,
    val team_lead_id: String,
    val name: String,
    val description: String,
    val demo_url: String?,
    val repo_url: String?,
    val tech_stack: List<String>,
    val storage_asset_ids: List<String>,
    val video_url: String?,
    val onchain_pda: String?,
    val status: String,
    val vote_count: Double,
)

data class HackathonCreateRequestDto(
    val title: String,
    val description: String,
    val prize_pool_usdc: Long,
    val voting_start: String,
    val voting_end: String,
    val signing_flow: String = "wallet_first",
)
data class HackathonCreateResponseDto(
    val hackathon: HackathonDto,
    val transaction_b64: String,
    val escrow_pda: String,
)
data class EscrowSetRequestDto(val escrow_pubkey: String, val onchain_pda: String)
data class EscrowFinalizeRequestDto(val signed_tx_b64: String, val escrow_pubkey: String)
data class EscrowFinalizeResponseDto(val hackathon: HackathonDto, val tx_signature: String)
data class RefundTxResponseDto(val transaction_b64: String)
data class RefundConfirmRequestDto(val tx_signature: String)

data class VotePrepareRequestDto(val project_id: String)
data class VotePrepareResponseDto(
    val vote_message: String,
    val vote_weight: Double,
    val voter_skr_staked: Long,
    val expires_at: String,
)

data class VoteConfirmRequestDto(val project_id: String, val vote_message: String, val tx_signature: String)
data class DeviceTokenDto(val token: String)
data class VoteResponseDto(
    val id: String,
    val voter_id: String,
    val project_id: String,
    val weight: Double,
    val tx_signature: String,
)

data class SupportNftPrepareRequestDto(val project_id: String)
data class SupportNftPrepareResponseDto(
    val transaction_b64: String,
    val amount_display: String,
    val project_name: String,
    val project_id: String,
)
data class SupportNftClaimRequestDto(val signed_tx_b64: String, val project_id: String)
data class SupportNftClaimResponseDto(val success: Boolean, val tx_signature: String)
data class SupportNftMineResponseDto(val project_ids: List<String>)

// ── API Interface ──────────────────────────────────────────────────────────

interface SeekerApi {

    @GET("users/challenge")
    suspend fun getChallenge(@Query("wallet_address") walletAddress: String): WalletChallengeDto

    @POST("users/login")
    suspend fun login(@Body body: UserCreateDto): AuthTokenDto

    @GET("users/me")
    suspend fun getMe(): UserDto

    @GET("hackathons/")
    suspend fun listHackathons(@Query("status") status: String? = null): List<HackathonDto>

    @GET("hackathons/{id}")
    suspend fun getHackathon(@Path("id") id: String): HackathonDto

    @POST("hackathons/")
    suspend fun createHackathon(@Body body: HackathonCreateRequestDto): HackathonCreateResponseDto

    @PATCH("hackathons/{id}/escrow")
    suspend fun setEscrow(@Path("id") id: String, @Body body: EscrowSetRequestDto): HackathonDto

    @POST("hackathons/{id}/escrow/finalize")
    suspend fun finalizeEscrow(@Path("id") id: String, @Body body: EscrowFinalizeRequestDto): EscrowFinalizeResponseDto

    @DELETE("hackathons/{id}")
    suspend fun deleteDraftHackathon(@Path("id") id: String)

    @GET("hackathons/{id}/verify/refund/release-tx")
    suspend fun getRefundTx(@Path("id") id: String): RefundTxResponseDto

    @POST("hackathons/{id}/verify/refund")
    suspend fun confirmRefund(@Path("id") id: String, @Body body: RefundConfirmRequestDto): HackathonDto

    @GET("projects/hackathon/{hackathonId}")
    suspend fun listProjects(@Path("hackathonId") hackathonId: String): List<ProjectDto>

    @GET("projects/{id}")
    suspend fun getProject(@Path("id") id: String): ProjectDto

    @POST("votes/prepare")
    suspend fun prepareVote(@Body body: VotePrepareRequestDto): VotePrepareResponseDto

    @POST("votes/confirm")
    suspend fun confirmVote(@Body body: VoteConfirmRequestDto): VoteResponseDto

    @GET("votes/mine")
    suspend fun getMyVotes(): List<String>

    @POST("mint/builder-pass/prepare")
    suspend fun prepareMint(): MintPrepareResponseDto

    @GET("mint/builder-pass/status")
    suspend fun getBuilderPassStatus(): BuilderPassStatusDto

    @POST("mint/builder-pass/claim")
    suspend fun claimBuilderPass(@Body body: MintClaimRequestDto): MintConfirmResponseDto

    @POST("users/device-token")
    suspend fun registerDeviceToken(@Body body: DeviceTokenDto)

    @DELETE("users/device-token")
    suspend fun deleteDeviceToken(@Body body: DeviceTokenDto)

    @POST("support-nft/prepare")
    suspend fun prepareSupportNft(@Body body: SupportNftPrepareRequestDto): SupportNftPrepareResponseDto

    @POST("support-nft/claim")
    suspend fun claimSupportNft(@Body body: SupportNftClaimRequestDto): SupportNftClaimResponseDto

    @GET("support-nft/mine")
    suspend fun getSupportNftsMine(@Query("hackathon_id") hackathonId: String): SupportNftMineResponseDto
}
