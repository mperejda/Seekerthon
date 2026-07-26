package com.alpinelabs.seekerthon.ui.screens.chat

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.alpinelabs.seekerthon.data.remote.SeekerApi
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import retrofit2.HttpException
import javax.inject.Inject

data class CherryChatUiState(
    val isLoading: Boolean = true,
    val error: String? = null,
    val token: String? = null,
    val sessionExpired: Boolean = false,
)

@HiltViewModel
class CherryChatViewModel @Inject constructor(
    private val api: SeekerApi,
) : ViewModel() {
    private val _state = MutableStateFlow(CherryChatUiState())
    val state: StateFlow<CherryChatUiState> = _state.asStateFlow()
    private var tokenJob: Job? = null

    init {
        loadToken()
    }

    fun loadToken() {
        if (tokenJob?.isActive == true) return
        tokenJob = viewModelScope.launch {
            _state.update { it.copy(isLoading = it.token == null, error = null) }
            runCatching { api.createCherryEmbedToken() }
                .onSuccess { response ->
                    _state.update {
                        it.copy(
                            isLoading = false,
                            token = response.token,
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

    private fun Throwable.readableMessage(): String {
        if (this is HttpException && code() == 401) return "Session expired. Please sign in again."
        return message ?: "Unable to load Cherry chat."
    }
}
