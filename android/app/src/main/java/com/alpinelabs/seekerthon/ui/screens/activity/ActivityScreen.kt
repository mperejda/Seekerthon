package com.alpinelabs.seekerthon.ui.screens.activity

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.HowToVote
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Stars
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import com.alpinelabs.seekerthon.data.remote.ActivitySupportNftDto
import com.alpinelabs.seekerthon.data.remote.ActivityVotedProjectDto

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ActivityScreen(
    onBack: () -> Unit,
    onSessionExpired: () -> Unit = {},
    viewModel: ActivityViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsState()

    if (state.sessionExpired) {
        LaunchedEffect(Unit) { onSessionExpired() }
    }

    Column(modifier = Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text("My Activity") },
            navigationIcon = {
                IconButton(onClick = onBack) {
                    Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "Back")
                }
            },
        )

        when {
            state.isLoading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
            state.error != null -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Text(state.error!!, color = MaterialTheme.colorScheme.error)
                    Button(onClick = { viewModel.load() }) {
                        Icon(Icons.Outlined.Refresh, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text("Retry")
                    }
                }
            }
            else -> LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                item {
                    SectionHeader(
                        icon = { Icon(Icons.Outlined.HowToVote, contentDescription = null, modifier = Modifier.size(18.dp)) },
                        title = "Projects Voted For",
                        count = state.votedProjects.size,
                    )
                }

                if (state.votedProjects.isEmpty()) {
                    item {
                        EmptyState("You haven't voted yet")
                    }
                } else {
                    items(state.votedProjects) { project ->
                        VotedProjectItem(project)
                    }
                }

                item { Spacer(Modifier.height(4.dp)) }

                item {
                    SectionHeader(
                        icon = { Icon(Icons.Outlined.Stars, contentDescription = null, modifier = Modifier.size(18.dp)) },
                        title = "Support NFTs Minted",
                        count = state.supportNfts.size,
                    )
                }

                if (state.supportNfts.isEmpty()) {
                    item {
                        EmptyState("No support NFTs minted yet")
                    }
                } else {
                    items(state.supportNfts) { nft ->
                        SupportNftItem(nft)
                    }
                }
            }
        }
    }
}

@Composable
private fun SectionHeader(
    icon: @Composable () -> Unit,
    title: String,
    count: Int,
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        icon()
        Text(title, fontWeight = FontWeight.Bold, fontSize = 15.sp, modifier = Modifier.weight(1f))
        Surface(
            shape = RoundedCornerShape(10.dp),
            color = MaterialTheme.colorScheme.secondaryContainer,
        ) {
            Text(
                count.toString(),
                fontSize = 12.sp,
                modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp),
                color = MaterialTheme.colorScheme.onSecondaryContainer,
            )
        }
    }
}

@Composable
private fun VotedProjectItem(project: ActivityVotedProjectDto) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
    ) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(project.project_name, fontWeight = FontWeight.Medium, fontSize = 14.sp)
            Text(project.hackathon_title, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun SupportNftItem(nft: ActivitySupportNftDto) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
    ) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(nft.project_name, fontWeight = FontWeight.Medium, fontSize = 14.sp)
            Text(nft.hackathon_title, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (nft.asset_id != null) {
                Text(
                    nft.asset_id.take(16) + "…",
                    fontSize = 11.sp,
                    color = MaterialTheme.colorScheme.outline,
                    fontWeight = FontWeight.Light,
                )
            }
        }
    }
}

@Composable
private fun EmptyState(message: String) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 16.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(message, fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
