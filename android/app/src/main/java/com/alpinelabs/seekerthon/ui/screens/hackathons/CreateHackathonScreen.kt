package com.alpinelabs.seekerthon.ui.screens.hackathons

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.alpinelabs.seekerthon.ui.LocalActivityResultSender
import java.time.Instant
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CreateHackathonScreen(
    onBack: () -> Unit,
    viewModel: CreateHackathonViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsState()
    val sender = LocalActivityResultSender.current

    if (state.success) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(16.dp),
                modifier = Modifier.padding(32.dp),
            ) {
                Text("🎉", style = MaterialTheme.typography.displayMedium)
                Text("Hackathon launched!", style = MaterialTheme.typography.headlineSmall)
                Text(
                    "Your hackathon is live and accepting submissions.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(8.dp))
                Button(onClick = onBack, modifier = Modifier.fillMaxWidth()) {
                    Text("Back to hackathons")
                }
            }
        }
        return
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Create Hackathon") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            OutlinedTextField(
                value = state.title,
                onValueChange = viewModel::setTitle,
                label = { Text("Title") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                enabled = !state.isLoading,
                keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
            )

            OutlinedTextField(
                value = state.description,
                onValueChange = viewModel::setDescription,
                label = { Text("Description") },
                modifier = Modifier.fillMaxWidth(),
                minLines = 3,
                enabled = !state.isLoading,
                keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
            )

            OutlinedTextField(
                value = state.prizeUsdc,
                onValueChange = viewModel::setPrizeUsdc,
                label = { Text("Prize pool (USDC)") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                enabled = !state.isLoading,
            )

            DateTimePicker(
                label = "Voting starts",
                millis = state.votingStartMillis,
                enabled = !state.isLoading,
                onPicked = viewModel::setVotingStart,
            )

            DateTimePicker(
                label = "Voting ends",
                millis = state.votingEndMillis,
                enabled = !state.isLoading,
                onPicked = viewModel::setVotingEnd,
            )

            if (state.error != null) {
                Text(
                    state.error!!,
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodySmall,
                )
            }

            Button(
                onClick = { viewModel.submit(sender) },
                enabled = !state.isLoading,
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (state.isLoading) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(16.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onPrimary,
                    )
                    Spacer(Modifier.width(8.dp))
                }
                Text(if (state.isLoading && state.step != null) state.step!! else "Create & Fund Escrow")
            }

            Spacer(Modifier.height(8.dp))
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DateTimePicker(
    label: String,
    millis: Long?,
    enabled: Boolean,
    onPicked: (Long) -> Unit,
) {
    val zone = ZoneId.systemDefault()
    val displayFormatter = DateTimeFormatter.ofPattern("MMM d, yyyy  h:mm a").withZone(zone)
    val displayText = millis?.let { displayFormatter.format(Instant.ofEpochMilli(it)) } ?: ""

    var showDatePicker by remember { mutableStateOf(false) }
    var showTimePicker by remember { mutableStateOf(false) }
    var pickedDate by remember { mutableStateOf<LocalDate?>(null) }

    val datePickerState = rememberDatePickerState(
        initialSelectedDateMillis = millis
    )
    val timePickerState = rememberTimePickerState(
        initialHour = millis?.let {
            Instant.ofEpochMilli(it).atZone(zone).hour
        } ?: 12,
        initialMinute = millis?.let {
            Instant.ofEpochMilli(it).atZone(zone).minute
        } ?: 0,
        is24Hour = false,
    )

    Box(Modifier.fillMaxWidth()) {
        OutlinedTextField(
            value = displayText,
            onValueChange = {},
            label = { Text(label) },
            modifier = Modifier.fillMaxWidth(),
            readOnly = true,
            enabled = enabled,
        )
        if (enabled) {
            Box(Modifier.matchParentSize().clickable { showDatePicker = true })
        }
    }

    if (showDatePicker) {
        DatePickerDialog(
            onDismissRequest = { showDatePicker = false },
            confirmButton = {
                TextButton(onClick = {
                    showDatePicker = false
                    val selectedMs = datePickerState.selectedDateMillis
                    if (selectedMs != null) {
                        pickedDate = Instant.ofEpochMilli(selectedMs).atZone(ZoneId.of("UTC")).toLocalDate()
                        showTimePicker = true
                    }
                }) { Text("Next") }
            },
            dismissButton = {
                TextButton(onClick = { showDatePicker = false }) { Text("Cancel") }
            },
        ) {
            DatePicker(state = datePickerState)
        }
    }

    if (showTimePicker && pickedDate != null) {
        AlertDialog(
            onDismissRequest = { showTimePicker = false },
            title = { Text("Select time") },
            text = {
                Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                    TimePicker(state = timePickerState)
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    showTimePicker = false
                    val date = pickedDate ?: return@TextButton
                    val time = LocalTime.of(timePickerState.hour, timePickerState.minute)
                    val epochMillis = date.atTime(time).atZone(zone).toInstant().toEpochMilli()
                    onPicked(epochMillis)
                }) { Text("OK") }
            },
            dismissButton = {
                TextButton(onClick = { showTimePicker = false }) { Text("Cancel") }
            },
        )
    }
}
