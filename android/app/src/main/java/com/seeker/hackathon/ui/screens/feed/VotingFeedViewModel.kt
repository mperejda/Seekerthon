package com.seeker.hackathon.ui.screens.feed

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.solana.mobilewalletadapter.clientlib.ActivityResultSender
import com.seeker.hackathon.data.remote.SeekerApi
import com.seeker.hackathon.data.remote.VoteConfirmRequestDto
import com.seeker.hackathon.data.remote.VotePrepareRequestDto
import com.seeker.hackathon.data.repository.WalletRepository
import com.seeker.hackathon.domain.model.Project
import com.seeker.hackathon.util.toProject
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

data class FeedUiState(
    val projects: List<Project> = emptyList(),
    val currentIndex: Int = 0,
    val isLoading: Boolean = false,
    val votedProjectIds: Set<String> = emptySet(),
    val votingProjectId: String? = null,
    val error: String? = null,
    val voteSuccessMessage: String? = null,
    val userMultiplier: Double = 1.0,
    val isSeekerVerified: Boolean = false,
)

@HiltViewModel
class VotingFeedViewModel @Inject constructor(
    private val api: SeekerApi,
    private val walletRepo: WalletRepository,
    savedStateHandle: SavedStateHandle,
) : ViewModel() {

    private val hackathonId: String = checkNotNull(savedStateHandle["hackathonId"])

    private val _state = MutableStateFlow(FeedUiState(isLoading = true))
    val state: StateFlow<FeedUiState> = _state.asStateFlow()

    init {
        loadProjects()
        loadUserState()
    }

    private fun loadProjects() {
        viewModelScope.launch {
            _state.value = _state.value.copy(isLoading = true, error = null)
            try {
                val projects = api.listProjects(hackathonId).map { it.toProject() }
                _state.value = _state.value.copy(projects = projects, isLoading = false)
            } catch (e: Exception) {
                _state.value = _state.value.copy(
                    isLoading = false,
                    error = "Failed to load projects: ${e.message}"
                )
            }
        }
    }

    private fun loadUserState() {
        viewModelScope.launch {
            try {
                val user = api.getMe()
                _state.value = _state.value.copy(
                    userMultiplier = user.vote_multiplier,
                    isSeekerVerified = user.is_seeker_verified,
                )
            } catch (_: Exception) {}
        }
        viewModelScope.launch {
            try {
                val voted = api.getMyVotes().toSet()
                _state.value = _state.value.copy(votedProjectIds = voted)
            } catch (_: Exception) {}
        }
    }

    fun onSwipeUp() {
        val projects = _state.value.projects
        if (projects.isEmpty()) return
        _state.value = _state.value.copy(
            currentIndex = (_state.value.currentIndex + 1).coerceAtMost(projects.size - 1)
        )
    }

    fun onSwipeDown() {
        _state.value = _state.value.copy(
            currentIndex = (_state.value.currentIndex - 1).coerceAtLeast(0)
        )
    }

    fun castVote(projectId: String, sender: ActivityResultSender) {
        if (_state.value.votedProjectIds.contains(projectId)) return

        viewModelScope.launch {
            _state.value = _state.value.copy(votingProjectId = projectId, error = null)

            try {
                // Step 1: Get vote message + locked weight from backend
                val prepare = api.prepareVote(VotePrepareRequestDto(project_id = projectId))

                // Step 2: Sign the message with Seeker wallet (no tx, no fees)
                val sigResult = walletRepo.signVoteMessage(sender, prepare.vote_message)
                val txSig = sigResult.getOrThrow()

                // Step 3: Confirm with backend — sends message + ed25519 sig
                val vote = api.confirmVote(VoteConfirmRequestDto(project_id = projectId, vote_message = prepare.vote_message, tx_signature = txSig))

                _state.value = _state.value.copy(
                    projects = _state.value.projects.map { p ->
                        if (p.id == projectId) p.copy(voteCount = p.voteCount + prepare.vote_weight)
                        else p
                    },
                    votedProjectIds = _state.value.votedProjectIds + projectId,
                    votingProjectId = null,
                    voteSuccessMessage = "Voted! Weight: ${prepare.vote_weight}×",
                )
            } catch (e: Exception) {
                _state.value = _state.value.copy(
                    votingProjectId = null,
                    error = e.message ?: "Vote failed",
                )
            }
        }
    }

    fun dismissError() {
        _state.value = _state.value.copy(error = null)
    }

    fun dismissSuccessMessage() {
        _state.value = _state.value.copy(voteSuccessMessage = null)
    }
}
