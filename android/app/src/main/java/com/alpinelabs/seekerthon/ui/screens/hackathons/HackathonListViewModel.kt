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
import java.time.Instant
import javax.inject.Inject

data class HackathonListUiState(
    val hackathons: List<Hackathon> = emptyList(),
    val visibleHackathons: List<Hackathon> = emptyList(),
    val selectedList: HackathonListFilter = HackathonListFilter.Active,
    val isLoading: Boolean = false,
    val isRefreshing: Boolean = false,
    val hasBuilderPass: Boolean = false,
    val builderPassAvailable: Boolean = true,
    val builderPassUnavailableMessage: String? = null,
    val isMinting: Boolean = false,
    val mintSuccess: Boolean = false,
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
                val me = try { api.getMe() } catch (_: Exception) { null }
                val builderPassStatus = try { api.getBuilderPassStatus() } catch (_: Exception) { null }
                _state.value = HackathonListUiState(
                    hackathons = hackathons,
                    visibleHackathons = hackathons.filterFor(_state.value.selectedList),
                    selectedList = _state.value.selectedList,
                    hasBuilderPass = me?.has_builder_pass ?: false,
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
                val me = try { api.getMe() } catch (_: Exception) { null }
                val builderPassStatus = try { api.getBuilderPassStatus() } catch (_: Exception) { null }
                _state.value = _state.value.copy(
                    hackathons = hackathons,
                    visibleHackathons = hackathons.filterFor(_state.value.selectedList),
                    hasBuilderPass = me?.has_builder_pass ?: _state.value.hasBuilderPass,
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
            } catch (e: Exception) {
                _state.value = _state.value.copy(isMinting = false, error = e.message ?: "Mint failed")
            }
        }
    }

    fun dismissError() { _state.value = _state.value.copy(error = null) }
    fun dismissMintSuccess() { _state.value = _state.value.copy(mintSuccess = false) }

    private fun List<Hackathon>.filterFor(filter: HackathonListFilter): List<Hackathon> {
        return when (filter) {
            HackathonListFilter.Active -> filterForActiveVoting()
            HackathonListFilter.Past -> filter { it.status == "completed" }
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
