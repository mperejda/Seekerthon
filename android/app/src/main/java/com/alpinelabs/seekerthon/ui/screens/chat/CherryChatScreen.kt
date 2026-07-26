package com.alpinelabs.seekerthon.ui.screens.chat

import android.annotation.SuppressLint
import android.content.ActivityNotFoundException
import android.content.Intent
import android.graphics.Bitmap
import android.net.Uri
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.webkit.WebViewAssetLoader
import com.alpinelabs.seekerthon.ui.LocalActivityResultSender
import com.solana.mobilewalletadapter.clientlib.ActivityResultSender
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import org.json.JSONObject

private const val CHAT_ASSET_URL = "https://appassets.androidplatform.net/assets/cherry/chat.html"
private const val CHERRY_APP_ID = "735413f4-d9a3-4b90-af2f-845ba3ea97cd"
private const val CHERRY_ROOM_ID = "e5150eb2-f0e2-4bd3-b092-b37053bd5594"
private const val CHERRY_EMBED_URL = "https://embed.cherry.fun"

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CherryChatScreen(
    onBack: () -> Unit,
    onSessionExpired: () -> Unit = {},
    viewModel: CherryChatViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsState()
    val sender = LocalActivityResultSender.current
    val scope = rememberCoroutineScope()
    var webView by remember { mutableStateOf<WebView?>(null) }
    var canGoBack by remember { mutableStateOf(false) }

    if (state.sessionExpired) {
        LaunchedEffect(Unit) { onSessionExpired() }
    }

    BackHandler(enabled = canGoBack) {
        webView?.goBack()
    }

    DisposableEffect(Unit) {
        onDispose {
            webView?.destroy()
            webView = null
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Chat") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    IconButton(onClick = {
                        webView?.reload() ?: viewModel.loadToken()
                    }) {
                        Icon(Icons.Outlined.Refresh, contentDescription = "Reload chat")
                    }
                },
            )
        },
    ) { padding ->
        when {
            state.isLoading -> LoadingState(modifier = Modifier.padding(padding))
            state.error != null -> ErrorState(
                message = state.error!!,
                onRetry = viewModel::loadToken,
                modifier = Modifier.padding(padding),
            )
            state.token != null && state.walletAddress != null -> {
                Box(
                    modifier = Modifier
                        .padding(padding)
                        .fillMaxSize(),
                ) {
                    CherryChatWebView(
                        token = state.token!!,
                        walletAddress = state.walletAddress!!,
                        sender = sender,
                        viewModel = viewModel,
                        scope = scope,
                        onWebViewCreated = { webView = it },
                        onCanGoBackChanged = { canGoBack = it },
                    )
                }
            }
        }
    }
}

@Composable
private fun LoadingState(modifier: Modifier = Modifier) {
    Box(modifier = modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            CircularProgressIndicator(modifier = Modifier.size(28.dp))
            Spacer(Modifier.height(12.dp))
            Text("Loading chat...", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun ErrorState(
    message: String,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Box(modifier = modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(
            modifier = Modifier.padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(message, color = MaterialTheme.colorScheme.error, textAlign = TextAlign.Center)
            Button(onClick = onRetry) {
                Icon(Icons.Outlined.Refresh, contentDescription = null)
                Spacer(Modifier.size(8.dp))
                Text("Retry")
            }
        }
    }
}

@SuppressLint("SetJavaScriptEnabled")
@Composable
private fun CherryChatWebView(
    token: String,
    walletAddress: String,
    sender: ActivityResultSender,
    viewModel: CherryChatViewModel,
    scope: CoroutineScope,
    onWebViewCreated: (WebView) -> Unit,
    onCanGoBackChanged: (Boolean) -> Unit,
) {
    val context = LocalContext.current
    var isLoading by remember { mutableStateOf(true) }

    Box(modifier = Modifier.fillMaxSize()) {
        AndroidView(
            modifier = Modifier.fillMaxSize(),
            factory = { viewContext ->
                val assetLoader = WebViewAssetLoader.Builder()
                    .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(viewContext))
                    .build()

                WebView(viewContext).apply {
                    settings.javaScriptEnabled = true
                    settings.domStorageEnabled = true
                    settings.allowFileAccess = false
                    settings.allowContentAccess = false
                    settings.mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
                    settings.mediaPlaybackRequiresUserGesture = false
                    CookieManager.getInstance().setAcceptCookie(true)
                    CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)

                    addJavascriptInterface(
                        CherryNativeBridge(
                            webView = this,
                            viewModel = viewModel,
                            sender = sender,
                            scope = scope,
                        ),
                        "CherryNative",
                    )

                    webChromeClient = WebChromeClient()
                    webViewClient = object : WebViewClient() {
                        override fun shouldInterceptRequest(
                            view: WebView,
                            request: WebResourceRequest,
                        ) = assetLoader.shouldInterceptRequest(request.url)

                        override fun shouldOverrideUrlLoading(
                            view: WebView,
                            request: WebResourceRequest,
                        ): Boolean {
                            val url = request.url
                            if (url.scheme == "http" || url.scheme == "https") {
                                return false
                            }

                            return try {
                                context.startActivity(Intent(Intent.ACTION_VIEW, url))
                                true
                            } catch (_: ActivityNotFoundException) {
                                true
                            }
                        }

                        override fun onPageStarted(view: WebView, url: String?, favicon: Bitmap?) {
                            isLoading = true
                            onCanGoBackChanged(view.canGoBack())
                        }

                        override fun onPageFinished(view: WebView, url: String?) {
                            isLoading = false
                            onCanGoBackChanged(view.canGoBack())
                        }
                    }

                    loadUrl(buildChatUrl(token, walletAddress))
                    onWebViewCreated(this)
                }
            },
        )

        if (isLoading) {
            LoadingState()
        }
    }
}

private class CherryNativeBridge(
    private val webView: WebView,
    private val viewModel: CherryChatViewModel,
    private val sender: ActivityResultSender,
    private val scope: CoroutineScope,
) {
    @JavascriptInterface
    fun signChallenge(id: String, messageBase64: String) {
        scope.launch {
            viewModel.signChallenge(sender, messageBase64)
                .onSuccess { signatureBase64 ->
                    evaluate("__cherryResolveSign(${quote(id)}, ${quote(signatureBase64)});")
                }
                .onFailure { error ->
                    evaluate("__cherryRejectSign(${quote(id)}, ${quote(error.message ?: "Wallet signing failed")});")
                }
        }
    }

    @JavascriptInterface
    fun walletConnectRequested() {
        scope.launch {
            viewModel.refreshAuth()
                .onSuccess { auth ->
                    evaluate("__cherryUpdateAuth(${quote(auth.token)}, ${quote(auth.walletAddress)});")
                }
        }
    }

    @JavascriptInterface
    fun onCherryEvent(payload: String) {
        // Hook for debug logging or analytics if needed; keep bridge available for host page events.
    }

    private fun evaluate(script: String) {
        webView.post {
            webView.evaluateJavascript(script, null)
        }
    }

    private fun quote(value: String): String = JSONObject.quote(value)
}

private fun buildChatUrl(token: String, walletAddress: String): String {
    return Uri.parse(CHAT_ASSET_URL)
        .buildUpon()
        .appendQueryParameter("appId", CHERRY_APP_ID)
        .appendQueryParameter("roomId", CHERRY_ROOM_ID)
        .appendQueryParameter("mode", "single")
        .appendQueryParameter("embedUrl", CHERRY_EMBED_URL)
        .appendQueryParameter("token", token)
        .appendQueryParameter("walletAddress", walletAddress)
        .build()
        .toString()
}
