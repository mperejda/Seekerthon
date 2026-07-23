package com.alpinelabs.seekerthon.ui.screens.activity

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.alpinelabs.seekerthon.data.remote.ActivitySupportNftDto
import com.alpinelabs.seekerthon.data.remote.ActivityVotedProjectDto
import com.alpinelabs.seekerthon.data.remote.SeekerApi
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import retrofit2.HttpException
import javax.inject.Inject

data class ActivityUiState(
    val isLoading: Boolean = true,
    val votedProjects: List<ActivityVotedProjectDto> = emptyList(),
    val supportNfts: List<ActivitySupportNftDto> = emptyList(),
    val sessionExpired: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class ActivityViewModel @Inject constructor(
    private val api: SeekerApi,
) : ViewModel() {

    private val _state = MutableStateFlow(ActivityUiState())
    val state: StateFlow<ActivityUiState> = _state.asStateFlow()

    init {
        load()
    }

    fun load() {
        viewModelScope.launch {
            _state.value = ActivityUiState(isLoading = true)
            try {
                val activity = api.getMyActivity()
                _state.value = ActivityUiState(
                    isLoading = false,
                    votedProjects = activity.voted_projects,
                    supportNfts = activity.support_nfts,
                )
            } catch (e: HttpException) {
                if (e.code() == 401) {
                    _state.value = ActivityUiState(isLoading = false, sessionExpired = true)
                } else {
                    _state.value = ActivityUiState(isLoading = false, error = e.message)
                }
            } catch (e: Exception) {
                _state.value = ActivityUiState(isLoading = false, error = e.message)
            }
        }
    }
}
