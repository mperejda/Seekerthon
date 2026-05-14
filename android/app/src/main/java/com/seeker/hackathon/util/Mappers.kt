package com.seeker.hackathon.util

import com.seeker.hackathon.data.remote.HackathonDto
import com.seeker.hackathon.data.remote.ProjectDto
import com.seeker.hackathon.data.remote.UserDto
import com.seeker.hackathon.domain.model.Hackathon
import com.seeker.hackathon.domain.model.Project
import com.seeker.hackathon.domain.model.User
import java.time.Instant

fun UserDto.toUser() = User(
    id = id,
    walletAddress = wallet_address,
    skrBalance = skr_balance,
    skrStaked = skr_staked,
    voteMultiplier = vote_multiplier,
    isSeekerVerified = is_seeker_verified,
    hasBuilderPass = has_builder_pass,
    createdAt = Instant.parse(created_at),
)

fun HackathonDto.toHackathon() = Hackathon(
    id = id,
    organizerId = organizer_id,
    title = title,
    description = description,
    prizeUsdc = prize_pool_usdc,
    escrowPubkey = escrow_pubkey,
    status = status,
    votingStart = Instant.parse(voting_start),
    votingEnd = Instant.parse(voting_end),
    projectCount = project_count,
)

fun ProjectDto.toProject() = Project(
    id = id,
    hackathonId = hackathon_id,
    teamLeadId = team_lead_id,
    name = name,
    description = description,
    demoUrl = demo_url,
    repoUrl = repo_url,
    techStack = tech_stack,
    storageAssetIds = storage_asset_ids,
    videoUrl = video_url,
    onchainPda = onchain_pda,
    status = status,
    voteCount = vote_count,
)
