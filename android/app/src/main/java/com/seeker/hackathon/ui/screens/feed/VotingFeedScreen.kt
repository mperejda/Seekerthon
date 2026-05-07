package com.seeker.hackathon.ui.screens.feed

import android.content.Intent
import android.net.Uri
import android.view.ViewGroup
import androidx.compose.animation.*
import androidx.compose.foundation.*
import androidx.compose.foundation.gestures.*
import androidx.compose.foundation.gestures.snapping.rememberSnapFlingBehavior
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.pulltorefresh.rememberPullToRefreshState
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.media3.common.MediaItem
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView
import coil.compose.AsyncImage
import android.webkit.WebView
import android.webkit.WebViewClient
import com.seeker.hackathon.domain.model.Project
import com.seeker.hackathon.ui.LocalActivityResultSender
import kotlinx.coroutines.launch

@OptIn(ExperimentalFoundationApi::class, ExperimentalMaterial3Api::class)
@Composable
fun VotingFeedScreen(
    hackathonId: String,
    viewModel: VotingFeedViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsState()
    val scope = rememberCoroutineScope()
    val activityResultSender = LocalActivityResultSender.current

    val listState = rememberLazyListState()

    // Snap scroll
    val flingBehavior = rememberSnapFlingBehavior(lazyListState = listState)

    Box(modifier = Modifier.fillMaxSize().background(Color.Black)) {
        if (state.isLoading) {
            CircularProgressIndicator(
                modifier = Modifier.align(Alignment.Center),
                color = Color.White
            )
        } else {
            PullToRefreshBox(
                isRefreshing = state.isRefreshing,
                onRefresh = { viewModel.refresh() },
                modifier = Modifier.fillMaxSize(),
            ) {
                LazyColumn(
                    state = listState,
                    flingBehavior = flingBehavior,
                    modifier = Modifier.fillMaxSize(),
                ) {
                    itemsIndexed(state.projects) { index, project ->
                        ProjectCard(
                            project = project,
                            isVoted = state.votedProjectIds.contains(project.id),
                            isVoting = state.votingProjectId == project.id,
                            userMultiplier = state.userMultiplier,
                            isSeekerVerified = state.isSeekerVerified,
                            onVote = { viewModel.castVote(project.id, activityResultSender) },
                            modifier = Modifier
                                .fillParentMaxHeight()
                                .fillMaxWidth(),
                        )
                    }
                    if (state.projects.isEmpty()) {
                        item {
                            Box(
                                modifier = Modifier
                                    .fillParentMaxHeight()
                                    .fillMaxWidth(),
                                contentAlignment = Alignment.Center,
                            ) {
                                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                    Icon(Icons.Outlined.Inbox, null, tint = Color.White, modifier = Modifier.size(48.dp))
                                    Spacer(Modifier.height(12.dp))
                                    Text("No projects yet", color = Color.White, fontSize = 18.sp)
                                }
                            }
                        }
                    }
                }
            }

            // Top overlay: hackathon name + vote power badge
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 48.dp)
                    .align(Alignment.TopStart),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                // Seeker verified badge
                if (state.isSeekerVerified) {
                    SeekerBadge()
                }
                Spacer(Modifier.weight(1f))
                VotePowerChip(multiplier = state.userMultiplier)
            }

            // Error snackbar
            state.error?.let { error ->
                Snackbar(
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .padding(16.dp),
                    action = {
                        TextButton(onClick = { viewModel.dismissError() }) {
                            Text("Dismiss", color = Color.White)
                        }
                    },
                    containerColor = MaterialTheme.colorScheme.errorContainer,
                ) {
                    Text(error, color = MaterialTheme.colorScheme.onErrorContainer)
                }
            }

            // Vote success toast
            AnimatedVisibility(
                visible = state.voteSuccessMessage != null,
                enter = fadeIn() + slideInVertically(),
                exit = fadeOut(),
                modifier = Modifier.align(Alignment.BottomCenter),
            ) {
                state.voteSuccessMessage?.let { msg ->
                    LaunchedEffect(msg) {
                        kotlinx.coroutines.delay(2000)
                        viewModel.dismissSuccessMessage()
                    }
                    Card(
                        modifier = Modifier.padding(16.dp),
                        colors = CardDefaults.cardColors(containerColor = Color(0xFF1DB954)),
                    ) {
                        Row(
                            modifier = Modifier.padding(12.dp, 8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Icon(Icons.Filled.CheckCircle, null, tint = Color.White)
                            Text(msg, color = Color.White, fontWeight = FontWeight.Medium)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun ProjectCard(
    project: Project,
    isVoted: Boolean,
    isVoting: Boolean,
    userMultiplier: Double,
    isSeekerVerified: Boolean,
    onVote: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current

    val youtubeId = project.demoUrl?.let { extractYouTubeId(it) }
    var youtubeIsPlaying by remember { mutableStateOf(false) }

    Box(modifier = modifier) {
        // Background: YouTube embed, mp4, image, or gradient placeholder
        when {
            youtubeId != null -> if (youtubeIsPlaying) {
                YouTubeWebPlayer(
                    videoId = youtubeId,
                    modifier = Modifier.fillMaxSize(),
                )
            } else {
                YouTubeThumbnail(
                    videoId = youtubeId,
                    onPlay = { youtubeIsPlaying = true },
                    modifier = Modifier.fillMaxSize(),
                )
            }
            project.demoUrl?.endsWith(".mp4") == true || project.demoUrl?.contains("video") == true -> VideoPlayer(
                url = project.demoUrl,
                modifier = Modifier.fillMaxSize(),
            )
            project.storageAssetIds.isNotEmpty() -> AsyncImage(
                model = project.storageAssetIds.first(),
                contentDescription = project.name,
                modifier = Modifier.fillMaxSize(),
                contentScale = ContentScale.Crop,
            )
            else -> Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(Brush.verticalGradient(colors = listOf(Color(0xFF1A0533), Color(0xFF0A1A33))))
            )
        }

        // Scrim for readability
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(
                    Brush.verticalGradient(
                        colors = listOf(Color.Transparent, Color(0xCC000000)),
                        startY = 300f,
                    )
                )
        )

        // Right side action buttons
        Column(
            modifier = Modifier
                .align(Alignment.CenterEnd)
                .padding(end = 12.dp)
                .padding(bottom = 80.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(20.dp),
        ) {
            // Vote button
            ActionButton(
                icon = if (isVoted) Icons.Filled.Star else Icons.Outlined.StarOutline,
                label = "${project.voteCount.toLong()}",
                tint = if (isVoted) Color(0xFFFFD700) else Color.White,
                isLoading = isVoting,
                onClick = { if (!isVoted && !isVoting) onVote() },
            )

            // GitHub link
            if (project.repoUrl != null) {
                ActionButton(
                    icon = Icons.Outlined.Code,
                    label = "Repo",
                    tint = Color.White,
                    onClick = {
                        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(project.repoUrl)))
                    },
                )
            }

            // Demo link
            if (project.demoUrl != null && !project.demoUrl.endsWith(".mp4")) {
                ActionButton(
                    icon = Icons.Outlined.OpenInBrowser,
                    label = "Demo",
                    tint = Color.White,
                    onClick = {
                        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(project.demoUrl)))
                    },
                )
            }
        }

        // Bottom info panel
        Column(
            modifier = Modifier
                .align(Alignment.BottomStart)
                .padding(start = 16.dp, end = 72.dp, bottom = 80.dp),
        ) {
            Text(
                text = project.name,
                color = Color.White,
                fontSize = 20.sp,
                fontWeight = FontWeight.Bold,
            )
            Spacer(Modifier.height(4.dp))
            Text(
                text = project.description,
                color = Color.White.copy(alpha = 0.85f),
                fontSize = 13.sp,
                maxLines = 3,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.height(8.dp))
            // Tech stack chips
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                project.techStack.take(3).forEach { tech ->
                    TechChip(tech)
                }
            }
        }
    }
}

@Composable
private fun ActionButton(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: String,
    tint: Color,
    isLoading: Boolean = false,
    onClick: () -> Unit,
) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Box(
            modifier = Modifier
                .size(48.dp)
                .clip(CircleShape)
                .background(Color.Black.copy(alpha = 0.35f))
                .clickable(enabled = !isLoading) { onClick() },
            contentAlignment = Alignment.Center,
        ) {
            if (isLoading) {
                CircularProgressIndicator(modifier = Modifier.size(22.dp), color = tint, strokeWidth = 2.dp)
            } else {
                Icon(icon, contentDescription = label, tint = tint, modifier = Modifier.size(26.dp))
            }
        }
        Text(label, color = Color.White, fontSize = 11.sp, fontWeight = FontWeight.Medium)
    }
}

@Composable
private fun TechChip(label: String) {
    Surface(
        shape = RoundedCornerShape(20.dp),
        color = Color.White.copy(alpha = 0.18f),
    ) {
        Text(
            text = label,
            color = Color.White,
            fontSize = 11.sp,
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
        )
    }
}

@Composable
private fun SeekerBadge() {
    Surface(
        shape = RoundedCornerShape(20.dp),
        color = Color(0xFF534AB7).copy(alpha = 0.85f),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Icon(Icons.Filled.Verified, null, tint = Color(0xFFAFA9EC), modifier = Modifier.size(14.dp))
            Text("Seeker", color = Color(0xFFAFA9EC), fontSize = 11.sp, fontWeight = FontWeight.Medium)
        }
    }
}

@Composable
private fun VotePowerChip(multiplier: Double) {
    Surface(
        shape = RoundedCornerShape(20.dp),
        color = Color(0xFF1A1A2A).copy(alpha = 0.9f),
        border = BorderStroke(1.dp, Color(0xFF534AB7)),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Icon(Icons.Filled.Bolt, null, tint = Color(0xFFAFA9EC), modifier = Modifier.size(14.dp))
            Text(
                "%.1fx votes".format(multiplier),
                color = Color(0xFFAFA9EC),
                fontSize = 11.sp,
                fontWeight = FontWeight.Medium,
            )
        }
    }
}

private fun extractYouTubeId(url: String): String? {
    val patterns = listOf(
        Regex("""youtu\.be/([a-zA-Z0-9_-]{11})"""),
        Regex("""youtube\.com/watch\?.*v=([a-zA-Z0-9_-]{11})"""),
        Regex("""youtube\.com/embed/([a-zA-Z0-9_-]{11})"""),
        Regex("""youtube\.com/shorts/([a-zA-Z0-9_-]{11})"""),
    )
    for (pattern in patterns) {
        pattern.find(url)?.let { return it.groupValues[1] }
    }
    return null
}

@Composable
private fun YouTubeThumbnail(videoId: String, onPlay: () -> Unit, modifier: Modifier = Modifier) {
    Box(modifier = modifier) {
        AsyncImage(
            model = "https://img.youtube.com/vi/$videoId/maxresdefault.jpg",
            contentDescription = null,
            modifier = Modifier.fillMaxSize(),
            contentScale = ContentScale.Crop,
        )
        // Dark scrim + play button
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Color.Black.copy(alpha = 0.25f))
                .clickable(onClick = onPlay),
            contentAlignment = Alignment.Center,
        ) {
            Box(
                modifier = Modifier
                    .size(72.dp)
                    .clip(CircleShape)
                    .background(Color(0xCCFF0000)),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    Icons.Filled.PlayArrow,
                    contentDescription = "Play",
                    tint = Color.White,
                    modifier = Modifier.size(44.dp),
                )
            }
        }
    }
}

@Composable
private fun YouTubeWebPlayer(videoId: String, modifier: Modifier = Modifier) {
    var webView by remember { mutableStateOf<WebView?>(null) }

    AndroidView(
        factory = { context ->
            WebView(context).also { wv ->
                webView = wv
                wv.webViewClient = WebViewClient()
                wv.settings.apply {
                    javaScriptEnabled = true
                    domStorageEnabled = true
                    mediaPlaybackRequiresUserGesture = false
                    loadWithOverviewMode = true
                    useWideViewPort = true
                }
                wv.loadUrl(
                    "https://www.youtube.com/embed/$videoId" +
                    "?autoplay=1&playsinline=1&rel=0&controls=1&fs=1"
                )
            }
        },
        modifier = modifier,
    )

    DisposableEffect(Unit) {
        onDispose { webView?.destroy() }
    }
}

@Composable
private fun VideoPlayer(url: String, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val exoPlayer = remember {
        ExoPlayer.Builder(context).build().apply {
            setMediaItem(MediaItem.fromUri(url))
            repeatMode = ExoPlayer.REPEAT_MODE_ALL
            volume = 0f
            prepare()
            playWhenReady = true
        }
    }

    DisposableEffect(Unit) {
        onDispose { exoPlayer.release() }
    }

    AndroidView(
        factory = {
            PlayerView(it).apply {
                player = exoPlayer
                useController = false
                layoutParams = ViewGroup.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT,
                )
            }
        },
        modifier = modifier,
    )
}
