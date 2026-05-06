package com.seeker.hackathon.ui.screens.hackathons

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.seeker.hackathon.data.remote.SeekerApi
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
    val error: String? = null,
)

@HiltViewModel
class HackathonListViewModel @Inject constructor(
    private val api: SeekerApi,
) : ViewModel() {

    private val _state = MutableStateFlow(HackathonListUiState(isLoading = true))
    val state: StateFlow<HackathonListUiState> = _state.asStateFlow()

    init {
        load()
    }

    fun load() {
        viewModelScope.launch {
            _state.value = _state.value.copy(isLoading = true, error = null)
            try {
                val hackathons = api.listHackathons().map { it.toHackathon() }
                _state.value = HackathonListUiState(hackathons = hackathons)
            } catch (e: Exception) {
                _state.value = HackathonListUiState(error = e.message)
            }
        }
    }
}
