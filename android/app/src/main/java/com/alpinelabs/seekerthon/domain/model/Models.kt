package com.alpinelabs.seekerthon.domain.model

import java.time.Instant

data class User(
    val id: String,
    val walletAddress: String,
    val skrBalance: Long,
    val skrStaked: Long,
    val skrBalanceDisplay: String,
    val skrStakedDisplay: String,
    val voteMultiplier: Double,
    val isSeekerVerified: Boolean,
    val hasBuilderPass: Boolean,
    val createdAt: Instant,
)

data class Hackathon(
    val id: String,
    val organizerId: String,
    val title: String,
    val description: String,
    val prizeUsdc: Long,
    val escrowPubkey: String?,
    val status: String,
    val votingStart: Instant,
    val votingEnd: Instant,
    val projectCount: Int,
)

data class Project(
    val id: String,
    val hackathonId: String,
    val teamLeadId: String,
    val name: String,
    val description: String,
    val demoUrl: String?,
    val repoUrl: String?,
    val techStack: List<String>,
    val storageAssetIds: List<String>,
    val videoUrl: String?,
    val onchainPda: String?,
    val status: String,
    val voteCount: Double,
)

data class VotePrepareResult(
    val transactionB64: String,
    val voteWeight: Double,
    val voterSkrStaked: Long,
)

data class AuthState(
    val token: String,
    val user: User,
)
