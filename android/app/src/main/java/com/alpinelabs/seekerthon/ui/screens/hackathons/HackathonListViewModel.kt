package com.alpinelabs.seekerthon.ui.screens.hackathons

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.solana.mobilewalletadapter.clientlib.ActivityResultSender
import com.alpinelabs.seekerthon.data.remote.MintClaimRequestDto
import com.alpinelabs.seekerthon.data.remote.SeekerApi
import com.alpinelabs.seekerthon.data.repository.WalletRepository
import com.alpinelabs.seekerthon.domain.model.Hackathon
import com.alpinelabs.seekerthon.util.toHackathon
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import org.json.JSONObject
import retrofit2.HttpException
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import javax.inject.Inject

data class HackathonListUiState(
    val hackathons: List<Hackathon> = emptyList(),
    val visibleHackathons: List<Hackathon> = emptyList(),
    val selectedList: HackathonListFilter = HackathonListFilter.Active,
    val isLoading: Boolean = false,
    val isRefreshing: Boolean = false,
    val hasBuilderPass: Boolean = false,
    val voteMultiplier: Double = 1.0,
    val skrId: String? = null,
    val skrStaked: Long = 0L,
    val skrStakedRank: Int? = null,
    val skrStakedPercentile: Int? = null,
    val isSeekerVerified: Boolean = false,
    val votesCast: Int = 0,
    val hackathonsVoted: Int = 0,
    val memberSince: String? = null,
    val builderPassAvailable: Boolean = true,
    val builderPassUnavailableMessage: String? = null,
    val isMinting: Boolean = false,
    val mintSuccess: Boolean = false,
    val sessionExpired: Boolean = false,
    val error: String? = null,
)

enum class HackathonListFilter {
    Active,
    Past,
}

@HiltViewModel
class HackathonListViewModel @Inject constructor(
    private val api: SeekerApi,
    private val walletRepo: WalletRepository,
) : ViewModel() {

    private val _state = MutableStateFlow(HackathonListUiState(isLoading = true))
    val state: StateFlow<HackathonListUiState> = _state.asStateFlow()

    init {
        load()
    }

    fun signOut(onComplete: () -> Unit) {
        viewModelScope.launch {
            walletRepo.logout()
            onComplete()
        }
    }

    fun load() {
        viewModelScope.launch {
            _state.value = _state.value.copy(isLoading = true, error = null)
            try {
                val hackathons = api.listHackathons().map { it.toHackathon() }
                val me = try {
                    api.getMe()
                } catch (e: HttpException) {
                    if (e.code() == 401) {
                        _state.value = _state.value.copy(isLoading = false, sessionExpired = true)
                        return@launch
                    }
                    null
                } catch (_: Exception) { null }
                val builderPassStatus = try { api.getBuilderPassStatus() } catch (_: Exception) { null }
                _state.value = HackathonListUiState(
                    hackathons = hackathons,
                    visibleHackathons = hackathons.filterFor(_state.value.selectedList),
                    selectedList = _state.value.selectedList,
                    hasBuilderPass = me?.has_builder_pass ?: false,
                    voteMultiplier = me?.vote_multiplier ?: 1.0,
                    skrId = me?.skr_id,
                    skrStaked = me?.skr_staked ?: 0L,
                    skrStakedRank = me?.skr_staked_rank,
                    skrStakedPercentile = me?.skr_staked_percentile,
                    isSeekerVerified = me?.is_seeker_verified ?: false,
                    votesCast = me?.votes_cast ?: 0,
                    hackathonsVoted = me?.hackathons_voted ?: 0,
                    memberSince = me?.created_at?.let { formatMemberSince(it) },
                    builderPassAvailable = builderPassStatus?.available ?: true,
                    builderPassUnavailableMessage = builderPassStatus?.message?.takeIf { it.isNotBlank() },
                )
            } catch (e: Exception) {
                _state.value = HackathonListUiState(error = e.message)
            }
        }
    }

    fun refresh() {
        viewModelScope.launch {
            _state.value = _state.value.copy(isRefreshing = true, error = null)
            try {
                val hackathons = api.listHackathons().map { it.toHackathon() }
                val me = try {
                    api.getMe()
                } catch (e: HttpException) {
                    if (e.code() == 401) {
                        _state.value = _state.value.copy(isRefreshing = false, sessionExpired = true)
                        return@launch
                    }
                    null
                } catch (_: Exception) { null }
                val builderPassStatus = try { api.getBuilderPassStatus() } catch (_: Exception) { null }
                _state.value = _state.value.copy(
                    hackathons = hackathons,
                    visibleHackathons = hackathons.filterFor(_state.value.selectedList),
                    hasBuilderPass = me?.has_builder_pass ?: _state.value.hasBuilderPass,
                    voteMultiplier = me?.vote_multiplier ?: _state.value.voteMultiplier,
                    skrId = me?.skr_id ?: _state.value.skrId,
                    skrStaked = me?.skr_staked ?: _state.value.skrStaked,
                    skrStakedRank = me?.skr_staked_rank ?: _state.value.skrStakedRank,
                    skrStakedPercentile = me?.skr_staked_percentile ?: _state.value.skrStakedPercentile,
                    isSeekerVerified = me?.is_seeker_verified ?: _state.value.isSeekerVerified,
                    votesCast = me?.votes_cast ?: _state.value.votesCast,
                    hackathonsVoted = me?.hackathons_voted ?: _state.value.hackathonsVoted,
                    memberSince = me?.created_at?.let { formatMemberSince(it) } ?: _state.value.memberSince,
                    builderPassAvailable = builderPassStatus?.available ?: _state.value.builderPassAvailable,
                    builderPassUnavailableMessage = builderPassStatus?.message
                        ?.takeIf { it.isNotBlank() }
                        ?: if (builderPassStatus?.available == true) null else _state.value.builderPassUnavailableMessage,
                    isRefreshing = false,
                )
            } catch (e: Exception) {
                _state.value = _state.value.copy(isRefreshing = false, error = e.message)
            }
        }
    }

    fun selectList(filter: HackathonListFilter) {
        _state.value = _state.value.copy(
            selectedList = filter,
            visibleHackathons = _state.value.hackathons.filterFor(filter),
        )
    }

    fun mintBuilderPass(sender: ActivityResultSender) {
        viewModelScope.launch {
            _state.value = _state.value.copy(isMinting = true, error = null)
            try {
                if (!_state.value.builderPassAvailable) {
                    _state.value = _state.value.copy(
                        isMinting = false,
                        error = _state.value.builderPassUnavailableMessage
                            ?: "Builder Pass minting is temporarily unavailable.",
                    )
                    return@launch
                }
                // Step 1: get a buyer-only payment tx from backend
                val prepare = api.prepareMint()
                // Step 2: wallet signs the clean payment tx and returns the signed bytes
                val signedTxB64 = walletRepo.signAndSendTransaction(sender, prepare.transaction_b64).getOrThrow()
                // Step 3: backend submits payment, verifies buyer-paid fees, then mints the NFT
                api.claimBuilderPass(MintClaimRequestDto(signed_tx_b64 = signedTxB64, mint_pubkey = prepare.mint_pubkey))
                _state.value = _state.value.copy(isMinting = false, hasBuilderPass = true, mintSuccess = true)
            } catch (e: HttpException) {
                val detail = try {
                    JSONObject(e.response()?.errorBody()?.string() ?: "").getString("detail")
                } catch (_: Exception) { e.message ?: "Mint failed" }
                _state.value = _state.value.copy(isMinting = false, error = detail)
            } catch (e: Exception) {
                _state.value = _state.value.copy(isMinting = false, error = e.message ?: "Mint failed")
            }
        }
    }

    fun dismissError() { _state.value = _state.value.copy(error = null) }
    fun dismissMintSuccess() { _state.value = _state.value.copy(mintSuccess = false) }

    private fun formatMemberSince(isoTimestamp: String): String = try {
        val instant = Instant.parse(isoTimestamp)
        DateTimeFormatter.ofPattern("MMM yyyy").withZone(ZoneId.systemDefault()).format(instant)
    } catch (_: Exception) { "" }

    private fun List<Hackathon>.filterFor(filter: HackathonListFilter): List<Hackathon> {
        val now = Instant.now()
        return when (filter) {
            HackathonListFilter.Active -> filterForActiveVoting()
            HackathonListFilter.Past -> filter { hackathon ->
                hackathon.status == "completed" ||
                    (hackathon.status != "draft" && !now.isBefore(hackathon.votingEnd))
            }
        }
    }

    private fun List<Hackathon>.filterForActiveVoting(): List<Hackathon> {
        val now = Instant.now()
        return filter { hackathon ->
            when (hackathon.status) {
                "open" -> true  // funded, accepting submissions — show regardless of voting window
                "voting", "verifying" -> now < hackathon.votingEnd
                else -> false
            }
        }
    }
}
