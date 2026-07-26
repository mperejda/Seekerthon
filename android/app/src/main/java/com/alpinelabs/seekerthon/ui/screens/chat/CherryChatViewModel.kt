package com.alpinelabs.seekerthon.ui.screens.chat

import android.util.Base64
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.alpinelabs.seekerthon.data.remote.SeekerApi
import com.alpinelabs.seekerthon.data.repository.WalletRepository
import com.solana.mobilewalletadapter.clientlib.ActivityResultSender
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import retrofit2.HttpException
import javax.inject.Inject

data class CherryChatUiState(
    val isLoading: Boolean = true,
    val error: String? = null,
    val token: String? = null,
    val walletAddress: String? = null,
    val sessionExpired: Boolean = false,
)

@HiltViewModel
class CherryChatViewModel @Inject constructor(
    private val api: SeekerApi,
    private val walletRepository: WalletRepository,
) : ViewModel() {
    private val _state = MutableStateFlow(CherryChatUiState())
    val state: StateFlow<CherryChatUiState> = _state.asStateFlow()

    init {
        loadToken()
    }

    fun loadToken() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            runCatching { api.createCherryEmbedToken() }
                .onSuccess { response ->
                    _state.update {
                        it.copy(
                            isLoading = false,
                            token = response.token,
                            walletAddress = response.wallet_address,
                            sessionExpired = false,
                        )
                    }
                }
                .onFailure { error ->
                    _state.update {
                        it.copy(
                            isLoading = false,
                            error = error.readableMessage(),
                            sessionExpired = error is HttpException && error.code() == 401,
                        )
                    }
                }
        }
    }

    suspend fun refreshAuth(): Result<CherryAuthPayload> =
        runCatching {
            val response = api.createCherryEmbedToken()
            _state.update {
                it.copy(
                    token = response.token,
                    walletAddress = response.wallet_address,
                    sessionExpired = false,
                    error = null,
                )
            }
            CherryAuthPayload(token = response.token, walletAddress = response.wallet_address)
        }

    suspend fun signChallenge(
        sender: ActivityResultSender,
        messageBase64: String,
    ): Result<String> {
        val message = Base64.decode(messageBase64, Base64.DEFAULT)
        val expectedWalletAddress = state.value.walletAddress
            ?: return Result.failure(Exception("Missing authenticated wallet address"))
        return walletRepository.signCherryChallenge(sender, message, expectedWalletAddress)
            .map { signature ->
                Base64.encodeToString(signature, Base64.NO_WRAP)
            }
    }

    private fun Throwable.readableMessage(): String {
        if (this is HttpException && code() == 401) return "Session expired. Please sign in again."
        return message ?: "Unable to load Cherry chat."
    }
}

data class CherryAuthPayload(
    val token: String,
    val walletAddress: String,
)
