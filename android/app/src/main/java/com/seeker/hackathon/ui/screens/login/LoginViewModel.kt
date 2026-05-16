package com.alpinelabs.seekerthon.ui.screens.login

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.solana.mobilewalletadapter.clientlib.ActivityResultSender
import com.alpinelabs.seekerthon.data.repository.WalletRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

data class LoginUiState(
    val isLoading: Boolean = false,
    val isAuthenticated: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class LoginViewModel @Inject constructor(
    private val walletRepo: WalletRepository,
) : ViewModel() {

    private val _state = MutableStateFlow(LoginUiState(
        isAuthenticated = walletRepo.isLoggedIn()
    ))
    val state: StateFlow<LoginUiState> = _state.asStateFlow()

    fun connect(sender: ActivityResultSender) {
        viewModelScope.launch {
            _state.value = LoginUiState(isLoading = true)
            val result = walletRepo.connectAndLogin(sender)
            result.fold(
                onSuccess = {
                    _state.value = LoginUiState(isAuthenticated = true)
                },
                onFailure = { e ->
                    _state.value = LoginUiState(error = e.message ?: "Connection failed")
                },
            )
        }
    }
}
