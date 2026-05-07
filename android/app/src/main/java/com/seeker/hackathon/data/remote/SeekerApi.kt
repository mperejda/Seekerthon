package com.seeker.hackathon.data.remote

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
    val created_at: String,
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
    val onchain_pda: String?,
    val status: String,
    val vote_count: Double,
)

data class VotePrepareRequestDto(val project_id: String)
data class VotePrepareResponseDto(
    val vote_message: String,
    val vote_weight: Double,
    val voter_skr_staked: Long,
    val expires_at: String,
)

data class VoteConfirmRequestDto(val project_id: String, val vote_message: String, val tx_signature: String)
data class VoteResponseDto(
    val id: String,
    val voter_id: String,
    val project_id: String,
    val weight: Double,
    val tx_signature: String,
)

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

    @GET("projects/hackathon/{hackathonId}")
    suspend fun listProjects(@Path("hackathonId") hackathonId: String): List<ProjectDto>

    @GET("projects/{id}")
    suspend fun getProject(@Path("id") id: String): ProjectDto

    @POST("votes/prepare")
    suspend fun prepareVote(@Body body: VotePrepareRequestDto): VotePrepareResponseDto

    @POST("votes/confirm")
    suspend fun confirmVote(@Body body: VoteConfirmRequestDto): VoteResponseDto
}
