package com.alpinelabs.seekerthon.ui.screens.hackathons

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Diamond
import androidx.compose.material.icons.outlined.EmojiEvents
import androidx.compose.material.icons.outlined.Inbox
import androidx.compose.material.icons.outlined.Logout
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Timer
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import com.alpinelabs.seekerthon.domain.model.Hackathon
import com.alpinelabs.seekerthon.ui.LocalActivityResultSender
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HackathonListScreen(
    onHackathonClick: (String, Boolean) -> Unit,
    onSignOut: () -> Unit,
    onCreateHackathon: () -> Unit,
    viewModel: HackathonListViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsState()
    val sender = LocalActivityResultSender.current

    if (state.sessionExpired) {
        LaunchedEffect(Unit) { viewModel.signOut(onSignOut) }
    }

    // Success snackbar
    if (state.mintSuccess) {
        LaunchedEffect(Unit) { viewModel.dismissMintSuccess() }
    }

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
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Text(state.error!!, color = MaterialTheme.colorScheme.error)
                    Button(onClick = { viewModel.dismissError(); viewModel.load() }) {
                        Icon(Icons.Outlined.Refresh, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text("Retry")
                    }
                }
            }
            else -> Column(modifier = Modifier.fillMaxSize()) {
                PullToRefreshBox(
                    isRefreshing = state.isRefreshing,
                    onRefresh = { viewModel.refresh() },
                    modifier = Modifier.weight(1f),
                ) {
                    LazyColumn(
                        modifier = Modifier.fillMaxSize(),
                        contentPadding = PaddingValues(16.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        item {
                            HackathonListTabs(
                                selected = state.selectedList,
                                onSelected = viewModel::selectList,
                            )
                        }

                        if (state.visibleHackathons.isEmpty()) {
                            item {
                                Box(
                                    Modifier
                                        .fillParentMaxSize()
                                        .padding(bottom = 80.dp),
                                    contentAlignment = Alignment.Center,
                                ) {
                                    Column(
                                        horizontalAlignment = Alignment.CenterHorizontally,
                                        verticalArrangement = Arrangement.spacedBy(8.dp),
                                    ) {
                                        Icon(
                                            Icons.Outlined.Inbox,
                                            contentDescription = null,
                                            modifier = Modifier.size(48.dp),
                                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                        )
                                        Text(
                                            if (state.selectedList == HackathonListFilter.Past)
                                                "No completed hackathons yet"
                                            else
                                                "No active hackathons",
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        )
                                        if (state.selectedList == HackathonListFilter.Active) {
                                            Spacer(Modifier.height(8.dp))
                                            Button(onClick = onCreateHackathon) {
                                                Text("Create a Hackathon")
                                            }
                                        }
                                    }
                                }
                            }
                        } else {
                            items(state.visibleHackathons) { hackathon ->
                                HackathonCard(
                                    hackathon = hackathon,
                                    selectedList = state.selectedList,
                                    onClick = {
                                        onHackathonClick(
                                            hackathon.id,
                                            state.selectedList == HackathonListFilter.Past,
                                        )
                                    },
                                )
                            }
                        }
                    }
                }
                Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                    BuilderPassCard(
                        hasBuilderPass = state.hasBuilderPass,
                        builderPassAvailable = state.builderPassAvailable,
                        builderPassUnavailableMessage = state.builderPassUnavailableMessage,
                        isMinting = state.isMinting,
                        mintSuccess = state.mintSuccess,
                        onMint = { viewModel.mintBuilderPass(sender) },
                    )
                }
            }
        }
    }
}

@Composable
private fun BuilderPassCard(
    hasBuilderPass: Boolean,
    builderPassAvailable: Boolean,
    builderPassUnavailableMessage: String?,
    isMinting: Boolean,
    mintSuccess: Boolean,
    onMint: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (hasBuilderPass)
                MaterialTheme.colorScheme.secondaryContainer
            else
                MaterialTheme.colorScheme.surfaceVariant,
        ),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Icon(
                    Icons.Filled.Diamond,
                    contentDescription = null,
                    tint = if (hasBuilderPass) MaterialTheme.colorScheme.secondary else MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(20.dp),
                )
                Text(
                    "Alpine Labs Builder Pass",
                    fontWeight = FontWeight.Bold,
                    fontSize = 15.sp,
                )
                if (hasBuilderPass || mintSuccess) {
                    Spacer(Modifier.weight(1f))
                    Icon(
                        Icons.Filled.CheckCircle,
                        contentDescription = "Owned",
                        tint = MaterialTheme.colorScheme.secondary,
                        modifier = Modifier.size(18.dp),
                    )
                }
            }

            Text(
                when {
                    hasBuilderPass || mintSuccess ->
                        "You hold the Builder Pass — your vote power is 5× amplified."
                    !builderPassAvailable ->
                        builderPassUnavailableMessage ?: "Builder Pass minting is temporarily unavailable."
                    else ->
                        "5× vote boost on top of your SKR multiplier. Mint for $10 USDC."
                },
                fontSize = 13.sp,
                color = if (!hasBuilderPass && !mintSuccess && !builderPassAvailable)
                    MaterialTheme.colorScheme.error
                else
                    MaterialTheme.colorScheme.onSurfaceVariant,
            )

            if (!hasBuilderPass && !mintSuccess) {
                Button(
                    onClick = onMint,
                    enabled = !isMinting && builderPassAvailable,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(10.dp),
                ) {
                    if (isMinting) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(16.dp),
                            strokeWidth = 2.dp,
                            color = MaterialTheme.colorScheme.onPrimary,
                        )
                        Spacer(Modifier.width(8.dp))
                        Text("Minting…")
                    } else {
                        Text("Mint Alpine Labs Builder Pass for 5× vote boost")
                    }
                }
            }
        }
    }
}

@Composable
private fun HackathonListTabs(
    selected: HackathonListFilter,
    onSelected: (HackathonListFilter) -> Unit,
) {
    SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
        SegmentedButton(
            selected = selected == HackathonListFilter.Active,
            onClick = { onSelected(HackathonListFilter.Active) },
            shape = SegmentedButtonDefaults.itemShape(index = 0, count = 2),
        ) {
            Text("Voting")
        }
        SegmentedButton(
            selected = selected == HackathonListFilter.Past,
            onClick = { onSelected(HackathonListFilter.Past) },
            shape = SegmentedButtonDefaults.itemShape(index = 1, count = 2),
        ) {
            Text("Past")
        }
    }
}

@Composable
private fun HackathonCard(
    hackathon: Hackathon,
    selectedList: HackathonListFilter,
    onClick: () -> Unit,
) {
    val formatter = DateTimeFormatter.ofPattern("MMM d, h:mm a").withZone(ZoneId.systemDefault())
    val now = Instant.now()
    val isAcceptingSubmissions = hackathon.status == "open" && now.isBefore(hackathon.votingStart)

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .then(if (!isAcceptingSubmissions) Modifier.clickable(onClick = onClick) else Modifier),
        shape = RoundedCornerShape(12.dp),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(hackathon.title, fontWeight = FontWeight.Bold, fontSize = 16.sp, modifier = Modifier.weight(1f))
                StatusChip(selectedList = selectedList, isAcceptingSubmissions = isAcceptingSubmissions)
            }
            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                Icon(Icons.Outlined.EmojiEvents, null, modifier = Modifier.size(14.dp), tint = MaterialTheme.colorScheme.primary)
                Text(
                    "$%.2f USDC".format(hackathon.prizeUsdc / 1_000_000.0),
                    fontSize = 12.sp,
                    color = MaterialTheme.colorScheme.primary,
                )
            }
            Spacer(Modifier.height(4.dp))
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                Icon(Icons.Outlined.Timer, null, modifier = Modifier.size(14.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(
                    "Voting ${formatter.format(hackathon.votingStart)}–${formatter.format(hackathon.votingEnd)}",
                    fontSize = 12.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
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
private fun StatusChip(selectedList: HackathonListFilter, isAcceptingSubmissions: Boolean = false) {
    val (color, label) = when {
        selectedList == HackathonListFilter.Past ->
            Pair(MaterialTheme.colorScheme.secondaryContainer, "Complete")
        isAcceptingSubmissions ->
            Pair(MaterialTheme.colorScheme.primaryContainer, "Accepting submissions")
        else ->
            Pair(MaterialTheme.colorScheme.tertiaryContainer, "Voting in progress")
    }
    Surface(shape = RoundedCornerShape(20.dp), color = color) {
        Text(label, fontSize = 11.sp, modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp))
    }
}
