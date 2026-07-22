package com.alpinelabs.seekerthon.ui.screens.feed

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringSetPreferencesKey
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.solana.mobilewalletadapter.clientlib.ActivityResultSender
import com.alpinelabs.seekerthon.data.remote.RefundConfirmRequestDto
import com.alpinelabs.seekerthon.data.remote.SeekerApi
import com.alpinelabs.seekerthon.data.remote.SupportNftClaimRequestDto
import com.alpinelabs.seekerthon.data.remote.SupportNftPrepareRequestDto
import com.alpinelabs.seekerthon.data.remote.VoteConfirmRequestDto
import com.alpinelabs.seekerthon.data.remote.VotePrepareRequestDto
import com.alpinelabs.seekerthon.data.repository.WalletRepository
import com.alpinelabs.seekerthon.domain.model.Hackathon
import com.alpinelabs.seekerthon.domain.model.Project
import com.alpinelabs.seekerthon.util.toHackathon
import com.alpinelabs.seekerthon.util.toProject
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import org.json.JSONObject
import retrofit2.HttpException
import javax.inject.Inject

data class FeedUiState(
    val projects: List<Project> = emptyList(),
    val hackathon: Hackathon? = null,
    val currentIndex: Int = 0,
    val isLoading: Boolean = false,
    val isRefreshing: Boolean = false,
    val isUserStateLoaded: Boolean = false,
    val votedProjectIds: Set<String> = emptySet(),
    val votingProjectId: String? = null,
    val error: String? = null,
    val voteSuccessMessage: String? = null,
    val userMultiplier: Double = 1.0,
    val isSeekerVerified: Boolean = false,
    val hasFinishedVoting: Boolean = false,
    val currentUserId: String = "",
    val isRefunding: Boolean = false,
    val leaderboardOnly: Boolean = false,
    val supportedProjectIds: Set<String> = emptySet(),
    val mintingSupportProjectId: String? = null,
    val supportNftError: String? = null,
)

@HiltViewModel
class VotingFeedViewModel @Inject constructor(
    private val api: SeekerApi,
    private val walletRepo: WalletRepository,
    private val dataStore: DataStore<Preferences>,
    savedStateHandle: SavedStateHandle,
) : ViewModel() {

    private val hackathonId: String = checkNotNull(savedStateHandle["hackathonId"])
    private val leaderboardOnly: Boolean = savedStateHandle["leaderboardOnly"] ?: false

    // Set once getMe() resolves; used to scope finished-voting state per user
    private var walletAddress: String = ""

    private val _state = MutableStateFlow(FeedUiState(isLoading = true))
    val state: StateFlow<FeedUiState> = _state.asStateFlow()

    init {
        _state.value = _state.value.copy(leaderboardOnly = leaderboardOnly)
        loadProjects()
        loadUserState()
        if (leaderboardOnly) loadSupportNftsMine()
    }

    private fun loadProjects() {
        viewModelScope.launch {
            _state.value = _state.value.copy(isLoading = true, error = null)
            try {
                val projects = api.listProjects(hackathonId).map { it.toProject() }
                val hackathon = try { api.getHackathon(hackathonId).toHackathon() } catch (_: Exception) { null }
                _state.value = _state.value.copy(
                    projects = projects,
                    hackathon = hackathon,
                    hasFinishedVoting = _state.value.hasFinishedVoting ||
                        leaderboardOnly ||
                        hackathon?.status == "completed",
                    isLoading = false,
                )
            } catch (e: Exception) {
                _state.value = _state.value.copy(
                    isLoading = false,
                    error = "Failed to load projects: ${e.message}"
                )
            }
        }
    }

    fun refresh() {
        viewModelScope.launch {
            _state.value = _state.value.copy(isRefreshing = true, error = null)
            try {
                val projects = api.listProjects(hackathonId).map { it.toProject() }
                val voted = try { api.getMyVotes().toSet() } catch (_: Exception) { _state.value.votedProjectIds }
                val supported = if (leaderboardOnly) {
                    try { api.getSupportNftsMine(hackathonId).project_ids.toSet() }
                    catch (_: Exception) { _state.value.supportedProjectIds }
                } else _state.value.supportedProjectIds
                val hackathon = _state.value.hackathon
                _state.value = _state.value.copy(
                    projects = projects,
                    votedProjectIds = voted,
                    supportedProjectIds = supported,
                    hasFinishedVoting = _state.value.hasFinishedVoting ||
                        leaderboardOnly ||
                        hackathon?.status == "completed",
                    isRefreshing = false,
                )
            } catch (e: Exception) {
                _state.value = _state.value.copy(
                    isRefreshing = false,
                    error = "Failed to refresh: ${e.message}"
                )
            }
        }
    }

    private fun loadSupportNftsMine() {
        viewModelScope.launch {
            try {
                val ids = api.getSupportNftsMine(hackathonId).project_ids.toSet()
                _state.value = _state.value.copy(supportedProjectIds = ids)
            } catch (_: Exception) {}
        }
    }

    fun mintSupportNft(projectId: String, sender: ActivityResultSender) {
        if (_state.value.supportedProjectIds.contains(projectId)) return

        viewModelScope.launch {
            _state.value = _state.value.copy(mintingSupportProjectId = projectId, supportNftError = null)
            try {
                val prepare = api.prepareSupportNft(SupportNftPrepareRequestDto(project_id = projectId))
                val signResult = walletRepo.signAndSendMintTransaction(sender, prepare.transaction_b64)
                val signedTx = signResult.getOrThrow()
                api.claimSupportNft(SupportNftClaimRequestDto(signed_tx_b64 = signedTx, project_id = projectId))
                _state.value = _state.value.copy(
                    supportedProjectIds = _state.value.supportedProjectIds + projectId,
                    mintingSupportProjectId = null,
                )
            } catch (e: HttpException) {
                val detail = try {
                    org.json.JSONObject(e.response()?.errorBody()?.string() ?: "").getString("detail")
                } catch (_: Exception) { e.message ?: "Mint failed" }
                _state.value = _state.value.copy(mintingSupportProjectId = null, supportNftError = detail)
            } catch (e: Exception) {
                _state.value = _state.value.copy(mintingSupportProjectId = null, supportNftError = e.message ?: "Mint failed")
            }
        }
    }

    fun dismissSupportNftError() {
        _state.value = _state.value.copy(supportNftError = null)
    }

    private fun loadUserState() {
        viewModelScope.launch {
            try {
                val user = api.getMe()
                walletAddress = user.wallet_address
                val finished = dataStore.data.first()[FINISHED_VOTING_KEY] ?: emptySet()
                _state.value = _state.value.copy(
                    userMultiplier = user.vote_multiplier,
                    isSeekerVerified = user.is_seeker_verified,
                    hasFinishedVoting = _state.value.hasFinishedVoting ||
                        leaderboardOnly ||
                        finishedKey() in finished,
                    isUserStateLoaded = true,
                    currentUserId = user.id,
                )
            } catch (_: Exception) {
                _state.value = _state.value.copy(isUserStateLoaded = true)
            }
        }
        viewModelScope.launch {
            try {
                val voted = api.getMyVotes().toSet()
                _state.value = _state.value.copy(votedProjectIds = voted)
            } catch (_: Exception) {}
        }
    }

    fun finishVoting() {
        if (walletAddress.isEmpty()) return
        viewModelScope.launch {
            val key = finishedKey()
            dataStore.edit { prefs ->
                val current = prefs[FINISHED_VOTING_KEY] ?: emptySet()
                prefs[FINISHED_VOTING_KEY] = current + key
            }
            _state.value = _state.value.copy(hasFinishedVoting = true)
        }
        refresh()
    }

    private fun finishedKey() = "$walletAddress:$hackathonId"

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
                val prepare = api.prepareVote(VotePrepareRequestDto(project_id = projectId))
                val sigResult = walletRepo.signVoteMessage(sender, prepare.vote_message)
                val txSig = sigResult.getOrThrow()
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
            } catch (e: HttpException) {
                if (e.code() == 409) {
                    _state.value = _state.value.copy(
                        votedProjectIds = _state.value.votedProjectIds + projectId,
                        votingProjectId = null,
                        error = "You've already voted for this project",
                    )
                } else {
                    _state.value = _state.value.copy(
                        votingProjectId = null,
                        error = e.message ?: "Vote failed",
                    )
                }
            } catch (e: Exception) {
                _state.value = _state.value.copy(
                    votingProjectId = null,
                    error = e.message ?: "Vote failed",
                )
            }
        }
    }

    fun refundOrganizer(sender: ActivityResultSender) {
        viewModelScope.launch {
            _state.value = _state.value.copy(isRefunding = true, error = null)
            try {
                val refundTx = api.getRefundTx(hackathonId)
                val signResult = walletRepo.signAndSendMintTransaction(sender, refundTx.transaction_b64)
                val txSig = signResult.getOrElse { throw it }
                val updated = api.confirmRefund(hackathonId, RefundConfirmRequestDto(tx_signature = txSig))
                _state.value = _state.value.copy(hackathon = updated.toHackathon(), isRefunding = false)
            } catch (e: HttpException) {
                val detail = try {
                    JSONObject(e.response()?.errorBody()?.string() ?: "").getString("detail")
                } catch (_: Exception) { e.message ?: "Refund failed" }
                _state.value = _state.value.copy(isRefunding = false, error = detail)
            } catch (e: Exception) {
                _state.value = _state.value.copy(isRefunding = false, error = e.message ?: "Refund failed")
            }
        }
    }

    fun dismissError() {
        _state.value = _state.value.copy(error = null)
    }

    fun dismissSuccessMessage() {
        _state.value = _state.value.copy(voteSuccessMessage = null)
    }

    companion object {
        private val FINISHED_VOTING_KEY = stringSetPreferencesKey("finished_voting_hackathons")
    }
}
