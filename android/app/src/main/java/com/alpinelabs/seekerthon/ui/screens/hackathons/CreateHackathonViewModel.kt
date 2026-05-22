package com.alpinelabs.seekerthon.ui.screens.hackathons

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.solana.mobilewalletadapter.clientlib.ActivityResultSender
import com.alpinelabs.seekerthon.data.remote.EscrowSetRequestDto
import com.alpinelabs.seekerthon.data.remote.HackathonCreateRequestDto
import com.alpinelabs.seekerthon.data.remote.SeekerApi
import com.alpinelabs.seekerthon.data.repository.WalletRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import javax.inject.Inject

data class CreateHackathonUiState(
    val title: String = "",
    val description: String = "",
    val prizeUsdc: String = "",
    val votingStartMillis: Long? = null,
    val votingEndMillis: Long? = null,
    val step: String? = null,
    val isLoading: Boolean = false,
    val error: String? = null,
    val success: Boolean = false,
)

@HiltViewModel
class CreateHackathonViewModel @Inject constructor(
    private val api: SeekerApi,
    private val walletRepo: WalletRepository,
) : ViewModel() {

    private val _state = MutableStateFlow(CreateHackathonUiState())
    val state: StateFlow<CreateHackathonUiState> = _state.asStateFlow()

    fun setTitle(v: String) = _state.update { it.copy(title = v) }
    fun setDescription(v: String) = _state.update { it.copy(description = v) }
    fun setPrizeUsdc(v: String) = _state.update { it.copy(prizeUsdc = v) }
    fun setVotingStart(millis: Long) = _state.update { it.copy(votingStartMillis = millis) }
    fun setVotingEnd(millis: Long) = _state.update { it.copy(votingEndMillis = millis) }
    fun dismissError() = _state.update { it.copy(error = null) }

    fun submit(sender: ActivityResultSender) {
        val s = _state.value
        val prize = s.prizeUsdc.toDoubleOrNull()
        val startMs = s.votingStartMillis
        val endMs = s.votingEndMillis

        if (s.title.isBlank()) { _state.update { it.copy(error = "Title is required") }; return }
        if (s.description.isBlank()) { _state.update { it.copy(error = "Description is required") }; return }
        if (prize == null || prize <= 0) { _state.update { it.copy(error = "Enter a valid prize amount") }; return }
        if (startMs == null) { _state.update { it.copy(error = "Voting start date and time are required") }; return }
        if (endMs == null) { _state.update { it.copy(error = "Voting end date and time are required") }; return }
        if (endMs <= startMs) { _state.update { it.copy(error = "Voting end must be after voting start") }; return }

        _state.update { it.copy(isLoading = true, error = null) }

        viewModelScope.launch {
            try {
                val isoFormatter = DateTimeFormatter.ISO_INSTANT

                _state.update { it.copy(step = "Creating hackathon…") }
                val hackathon = api.createHackathon(
                    HackathonCreateRequestDto(
                        title = s.title.trim(),
                        description = s.description.trim(),
                        prize_pool_usdc = (prize * 1_000_000).toLong(),
                        voting_start = isoFormatter.format(Instant.ofEpochMilli(startMs).atOffset(ZoneOffset.UTC)),
                        voting_end = isoFormatter.format(Instant.ofEpochMilli(endMs).atOffset(ZoneOffset.UTC)),
                    )
                )

                _state.update { it.copy(step = "Building transaction…") }
                val escrowTx = api.createEscrowTx(hackathon.id)

                _state.update { it.copy(step = "Waiting for wallet approval…") }
                val signResult = walletRepo.signAndSendMintTransaction(sender, escrowTx.transaction_b64)
                signResult.getOrElse { throw it }

                _state.update { it.copy(step = "Opening hackathon…") }
                api.setEscrow(
                    hackathon.id,
                    EscrowSetRequestDto(
                        escrow_pubkey = escrowTx.escrow_pda,
                        onchain_pda = escrowTx.escrow_pda,
                    )
                )

                _state.update { it.copy(success = true, isLoading = false, step = null) }
            } catch (e: Exception) {
                _state.update { it.copy(error = e.message ?: "Something went wrong", isLoading = false, step = null) }
            }
        }
    }
}
