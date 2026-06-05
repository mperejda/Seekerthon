package com.alpinelabs.seekerthon.ui.screens.hackathons

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.solana.mobilewalletadapter.clientlib.ActivityResultSender
import com.alpinelabs.seekerthon.data.remote.EscrowFinalizeRequestDto
import com.alpinelabs.seekerthon.data.remote.HackathonCreateRequestDto
import com.alpinelabs.seekerthon.data.remote.SeekerApi
import com.alpinelabs.seekerthon.data.repository.WalletRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import org.json.JSONObject
import retrofit2.HttpException
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
            var hackathonId: String? = null
            var canCleanupDraft = true
            try {
                val isoFormatter = DateTimeFormatter.ISO_INSTANT

                _state.update { it.copy(step = "Creating hackathon…") }
                val response = api.createHackathon(
                    HackathonCreateRequestDto(
                        title = s.title.trim(),
                        description = s.description.trim(),
                        prize_pool_usdc = (prize * 1_000_000).toLong(),
                        voting_start = isoFormatter.format(Instant.ofEpochMilli(startMs).atOffset(ZoneOffset.UTC)),
                        voting_end = isoFormatter.format(Instant.ofEpochMilli(endMs).atOffset(ZoneOffset.UTC)),
                    )
                )
                hackathonId = response.hackathon.id

                _state.update { it.copy(step = "Waiting for wallet approval…") }
                val signedTxB64 = walletRepo.signAndSendTransaction(sender, response.transaction_b64).getOrThrow()

                _state.update { it.copy(step = "Funding escrow…") }
                canCleanupDraft = false
                api.finalizeEscrow(
                    response.hackathon.id,
                    EscrowFinalizeRequestDto(
                        signed_tx_b64 = signedTxB64,
                        escrow_pubkey = response.escrow_pda,
                    )
                )
                hackathonId = null // escrow set — no longer a draft to clean up

                _state.update { it.copy(success = true, isLoading = false, step = null) }
            } catch (e: HttpException) {
                if (canCleanupDraft) hackathonId?.let { runCatching { api.deleteDraftHackathon(it) } }
                val detail = try {
                    JSONObject(e.response()?.errorBody()?.string() ?: "").getString("detail")
                } catch (_: Exception) {
                    e.message ?: "Something went wrong"
                }
                _state.update { it.copy(error = detail, isLoading = false, step = null) }
            } catch (e: Exception) {
                if (canCleanupDraft) hackathonId?.let { runCatching { api.deleteDraftHackathon(it) } }
                _state.update { it.copy(error = e.message ?: "Something went wrong", isLoading = false, step = null) }
            }
        }
    }
}
