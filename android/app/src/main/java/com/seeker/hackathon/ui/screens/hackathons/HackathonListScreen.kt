package com.seeker.hackathon.ui.screens.hackathons

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.EmojiEvents
import androidx.compose.material.icons.outlined.Inbox
import androidx.compose.material.icons.outlined.Logout
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Timer
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import com.seeker.hackathon.domain.model.Hackathon
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HackathonListScreen(
    onHackathonClick: (String) -> Unit,
    onSignOut: () -> Unit,
    viewModel: HackathonListViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsState()

    Column(modifier = Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text("Seekerthon") },
            actions = {
                IconButton(onClick = { viewModel.signOut(onSignOut) }) {
                    Icon(Icons.Outlined.Logout, contentDescription = "Sign out")
                }
            },
        )

        when {
            state.isLoading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
            state.error != null -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text(state.error!!, color = MaterialTheme.colorScheme.error)
                    Button(onClick = { viewModel.load() }) {
                        Icon(Icons.Outlined.Refresh, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text("Retry")
                    }
                }
            }
            state.hackathons.isEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Icon(Icons.Outlined.Inbox, contentDescription = null, modifier = Modifier.size(48.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text("No hackathons yet", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            else -> LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                items(state.hackathons) { hackathon ->
                    HackathonCard(hackathon = hackathon, onClick = { onHackathonClick(hackathon.id) })
                }
            }
        }
    }
}

@Composable
private fun HackathonCard(hackathon: Hackathon, onClick: () -> Unit) {
    val formatter = DateTimeFormatter.ofPattern("MMM d").withZone(ZoneId.systemDefault())

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        shape = RoundedCornerShape(12.dp),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(hackathon.title, fontWeight = FontWeight.Bold, fontSize = 16.sp, modifier = Modifier.weight(1f))
                StatusChip(hackathon.status)
            }
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    Icon(Icons.Outlined.EmojiEvents, null, modifier = Modifier.size(14.dp), tint = MaterialTheme.colorScheme.primary)
                    Text(
                        "$%.2f USDC".format(hackathon.prizeUsdc / 1_000_000.0),
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.primary,
                    )
                }
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    Icon(Icons.Outlined.Timer, null, modifier = Modifier.size(14.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(
                        "Voting ${formatter.format(hackathon.votingStart)}–${formatter.format(hackathon.votingEnd)}",
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            Spacer(Modifier.height(4.dp))
            Text(
                "${hackathon.projectCount} projects",
                fontSize = 12.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun StatusChip(status: String) {
    val (color, label) = when (status) {
        "open" -> Pair(MaterialTheme.colorScheme.primaryContainer, "Open")
        "voting" -> Pair(MaterialTheme.colorScheme.tertiaryContainer, "Voting")
        "completed" -> Pair(MaterialTheme.colorScheme.secondaryContainer, "Done")
        else -> Pair(MaterialTheme.colorScheme.surfaceVariant, status.capitalize())
    }
    Surface(shape = RoundedCornerShape(20.dp), color = color) {
        Text(label, fontSize = 11.sp, modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp))
    }
}
