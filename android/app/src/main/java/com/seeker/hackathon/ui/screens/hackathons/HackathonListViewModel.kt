package com.seeker.hackathon.ui.screens.hackathons

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.seeker.hackathon.data.remote.SeekerApi
import com.seeker.hackathon.data.repository.WalletRepository
import com.seeker.hackathon.domain.model.Hackathon
import com.seeker.hackathon.util.toHackathon
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

data class HackathonListUiState(
    val hackathons: List<Hackathon> = emptyList(),
    val isLoading: Boolean = false,
    val isRefreshing: Boolean = false,
    val hasBuilderPass: Boolean = false,
    val isMinting: Boolean = false,
    val mintSuccess: Boolean = false,
    val error: String? = null,
)

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
                _state.value = HackathonListUiState(
                    hackathons = hackathons,
                    hasBuilderPass = me?.has_builder_pass ?: false,
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
                _state.value = _state.value.copy(
                    hackathons = hackathons,
                    hasBuilderPass = me?.has_builder_pass ?: _state.value.hasBuilderPass,
                    isRefreshing = false,
                )
            } catch (e: Exception) {
                _state.value = _state.value.copy(isRefreshing = false, error = e.message)
            }
        }
    }

    fun mintBuilderPass() {
        viewModelScope.launch {
            _state.value = _state.value.copy(isMinting = true, error = null)
            try {
                api.claimBuilderPass()
                _state.value = _state.value.copy(isMinting = false, hasBuilderPass = true, mintSuccess = true)
            } catch (e: Exception) {
                _state.value = _state.value.copy(isMinting = false, error = e.message ?: "Mint failed")
            }
        }
    }

    fun dismissError() { _state.value = _state.value.copy(error = null) }
    fun dismissMintSuccess() { _state.value = _state.value.copy(mintSuccess = false) }
}
