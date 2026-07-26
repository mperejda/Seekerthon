package com.alpinelabs.seekerthon.ui.screens.chat

import android.annotation.SuppressLint
import android.content.ActivityNotFoundException
import android.content.Intent
import android.graphics.Bitmap
import android.net.Uri
import android.util.Log
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.ConsoleMessage
import android.webkit.WebResourceError
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
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
import androidx.compose.material.icons.outlined.OpenInBrowser
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
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.webkit.WebViewAssetLoader
import org.json.JSONObject

private const val CHAT_ASSET_URL = "https://appassets.androidplatform.net/assets/cherry/chat.html"
private const val CHERRY_APP_ID = "735413f4-d9a3-4b90-af2f-845ba3ea97cd"
private const val CHERRY_ROOM_ID = "e5150eb2-f0e2-4bd3-b092-b37053bd5594"
private const val CHERRY_EMBED_URL = "https://embed.cherry.fun"
private const val CHERRY_LOG_TAG = "SeekerCherry"

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CherryChatScreen(
    onBack: () -> Unit,
    onSessionExpired: () -> Unit = {},
    viewModel: CherryChatViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsState()
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
                        webView?.context?.startActivity(
                            Intent(Intent.ACTION_VIEW, Uri.parse("https://cherry.fun"))
                        )
                    }) {
                        Icon(Icons.Outlined.OpenInBrowser, contentDescription = "Open Cherry")
                    }
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
            state.token != null -> {
                Box(
                    modifier = Modifier
                        .padding(padding)
                        .fillMaxSize(),
                ) {
                    CherryChatWebView(
                        token = state.token!!,
                        onDebug = {},
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
    onDebug: (String) -> Unit,
    onWebViewCreated: (WebView) -> Unit,
    onCanGoBackChanged: (Boolean) -> Unit,
) {
    val context = LocalContext.current
    var isLoading by remember { mutableStateOf(true) }
    var webError by remember { mutableStateOf<String?>(null) }

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
                            onDebug = onDebug,
                        ),
                        "CherryNative",
                    )

                    webChromeClient = object : WebChromeClient() {
                        override fun onConsoleMessage(consoleMessage: ConsoleMessage): Boolean {
                            val message = consoleMessage.message()
                            if (
                                consoleMessage.messageLevel() == ConsoleMessage.MessageLevel.ERROR ||
                                message.contains("Cherry", ignoreCase = true) ||
                                message.contains("cherry", ignoreCase = true)
                            ) {
                                webError = message
                                onDebug("Console: $message")
                            }
                            Log.d(CHERRY_LOG_TAG, "console ${consoleMessage.messageLevel()}: $message")
                            return true
                        }
                    }
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
                            webError = null
                            onDebug("WebView loading host page")
                            Log.d(CHERRY_LOG_TAG, "page started $url")
                            onCanGoBackChanged(view.canGoBack())
                        }

                        override fun onPageFinished(view: WebView, url: String?) {
                            isLoading = false
                            onDebug("WebView host loaded")
                            Log.d(CHERRY_LOG_TAG, "page finished $url")
                            onCanGoBackChanged(view.canGoBack())
                        }

                        override fun onReceivedError(
                            view: WebView,
                            request: WebResourceRequest,
                            error: WebResourceError,
                        ) {
                            if (request.isForMainFrame) {
                                val message = "WebView error: ${error.description}"
                                webError = message
                                onDebug(message)
                                Log.e(CHERRY_LOG_TAG, message)
                            }
                        }

                        override fun onReceivedHttpError(
                            view: WebView,
                            request: WebResourceRequest,
                            errorResponse: WebResourceResponse,
                        ) {
                            val url = request.url.toString()
                            if (url.contains("cherry", ignoreCase = true)) {
                                onDebug("HTTP ${errorResponse.statusCode}: ${request.url.host}")
                                Log.w(CHERRY_LOG_TAG, "HTTP ${errorResponse.statusCode}: $url")
                            }
                        }
                    }

                    loadUrl(buildChatUrl(token))
                    onWebViewCreated(this)
                }
            },
            update = { view ->
                view.evaluateJavascript("if (window.__cherryForceHeight) window.__cherryForceHeight(0);", null)
            },
        )

        if (isLoading) {
            LoadingState()
        } else if (webError != null) {
            WebErrorOverlay(message = webError!!)
        }
    }
}

@Composable
private fun WebErrorOverlay(message: String) {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.BottomCenter) {
        Text(
            text = message,
            modifier = Modifier.padding(16.dp),
            color = MaterialTheme.colorScheme.error,
            textAlign = TextAlign.Center,
        )
    }
}

private class CherryNativeBridge(
    private val onDebug: (String) -> Unit,
) {
    @JavascriptInterface
    fun onCherryEvent(payload: String) {
        val status = runCatching {
            val json = JSONObject(payload)
            val event = json.optString("event", "event")
            val data = json.opt("data")
            if (data == null || data == JSONObject.NULL) "Cherry: $event" else "Cherry: $event $data"
        }.getOrElse {
            "Cherry event"
        }
        Log.d(CHERRY_LOG_TAG, status)
        onDebug(status)
    }
}

private fun buildChatUrl(token: String): String {
    return Uri.parse(CHAT_ASSET_URL)
        .buildUpon()
        .appendQueryParameter("appId", CHERRY_APP_ID)
        .appendQueryParameter("roomId", CHERRY_ROOM_ID)
        .appendQueryParameter("mode", "single")
        .appendQueryParameter("embedUrl", CHERRY_EMBED_URL)
        .appendQueryParameter("token", token)
        .appendQueryParameter("viewportHeight", "900")
        .build()
        .toString()
}
