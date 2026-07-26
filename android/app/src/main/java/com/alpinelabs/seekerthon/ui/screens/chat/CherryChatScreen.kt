package com.alpinelabs.seekerthon.ui.screens.chat

import android.annotation.SuppressLint
import android.content.ActivityNotFoundException
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Color
import android.net.Uri
import android.util.Log
import android.webkit.ConsoleMessage
import android.webkit.CookieManager
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
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
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.OpenInBrowser
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
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.view.doOnLayout
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.webkit.WebViewAssetLoader
import androidx.webkit.WebViewCompat
import com.alpinelabs.seekerthon.BuildConfig
import org.json.JSONObject

private const val CHAT_ASSET_URL = "https://appassets.androidplatform.net/assets/cherry/chat.html"
private const val CHAT_ASSET_ORIGIN = "https://appassets.androidplatform.net"
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

    fun reloadChat() {
        viewModel.loadToken()
        webView?.reload()
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
                        runCatching {
                            webView?.context?.startActivity(
                                Intent(Intent.ACTION_VIEW, Uri.parse("https://cherry.fun")),
                            )
                        }
                    }) {
                        Icon(Icons.Outlined.OpenInBrowser, contentDescription = "Open Cherry")
                    }
                    IconButton(onClick = ::reloadChat) {
                        Icon(Icons.Outlined.Refresh, contentDescription = "Reload chat")
                    }
                },
            )
        },
    ) { padding ->
        when {
            state.token != null -> {
                Box(
                    modifier = Modifier
                        .padding(padding)
                        .imePadding()
                        .fillMaxSize(),
                ) {
                    CherryChatWebView(
                        token = state.token!!,
                        onTokenExpired = viewModel::loadToken,
                        onReloadRequested = ::reloadChat,
                        onWebViewCreated = { webView = it },
                        onCanGoBackChanged = { canGoBack = it },
                    )
                }
            }

            state.isLoading -> LoadingState(modifier = Modifier.padding(padding))

            state.error != null -> ErrorState(
                message = state.error!!,
                onRetry = viewModel::loadToken,
                modifier = Modifier.padding(padding),
            )
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
    onTokenExpired: () -> Unit,
    onReloadRequested: () -> Unit,
    onWebViewCreated: (WebView) -> Unit,
    onCanGoBackChanged: (Boolean) -> Unit,
) {
    val context = LocalContext.current
    val currentOnTokenExpired by rememberUpdatedState(onTokenExpired)
    val currentOnReloadRequested by rememberUpdatedState(onReloadRequested)
    var isLoading by remember { mutableStateOf(true) }
    var fatalError by remember { mutableStateOf<String?>(null) }

    val bridge = remember {
        CherryNativeBridge { event, data ->
            if (BuildConfig.DEBUG) Log.d(CHERRY_LOG_TAG, "event $event ${data ?: ""}")
            when (event) {
                "ready", "mounted" -> {
                    isLoading = false
                    fatalError = null
                }

                "authStateChange" -> {
                    if (data == true) fatalError = null
                }

                "tokenExpired" -> currentOnTokenExpired()
                "error" -> if (BuildConfig.DEBUG) {
                    Log.w(CHERRY_LOG_TAG, "Cherry embed error: ${cherryErrorMessage(data)}")
                }
            }
        }
    }

    DisposableEffect(bridge) {
        onDispose { bridge.detach() }
    }

    Box(modifier = Modifier.fillMaxSize()) {
        AndroidView(
            modifier = Modifier.fillMaxSize(),
            factory = { viewContext ->
                val assetLoader = WebViewAssetLoader.Builder()
                    .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(viewContext))
                    .build()

                WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)
                WebView(viewContext).apply {
                    setBackgroundColor(Color.rgb(10, 10, 18))
                    overScrollMode = WebView.OVER_SCROLL_NEVER
                    settings.javaScriptEnabled = true
                    settings.domStorageEnabled = true
                    settings.allowFileAccess = false
                    settings.allowContentAccess = false
                    settings.mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
                    settings.mediaPlaybackRequiresUserGesture = false
                    settings.setSupportMultipleWindows(false)
                    CookieManager.getInstance().setAcceptCookie(true)
                    CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)

                    bridge.attach(this)
                    WebViewCompat.addWebMessageListener(
                        this,
                        "CherryNative",
                        setOf(CHAT_ASSET_ORIGIN),
                    ) { sourceView, message, sourceOrigin, isMainFrame, _ ->
                        if (isMainFrame && sourceOrigin.toString() == CHAT_ASSET_ORIGIN) {
                            message.data?.let { bridge.postMessage(sourceView, it) }
                        }
                    }

                    webChromeClient = object : WebChromeClient() {
                        override fun onConsoleMessage(consoleMessage: ConsoleMessage): Boolean {
                            if (!BuildConfig.DEBUG) return true
                            val priority = if (
                                consoleMessage.messageLevel() == ConsoleMessage.MessageLevel.ERROR
                            ) Log.ERROR else Log.DEBUG
                            Log.println(
                                priority,
                                CHERRY_LOG_TAG,
                                "console ${consoleMessage.messageLevel()}: ${consoleMessage.message()}",
                            )
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
                            if (!request.isForMainFrame) return false
                            val url = request.url
                            if (url.toString() == CHAT_ASSET_URL) return false

                            if (url.scheme == "https") {
                                try {
                                    context.startActivity(Intent(Intent.ACTION_VIEW, url))
                                } catch (_: ActivityNotFoundException) {
                                    // No browser is available; keep the untrusted URL out of the WebView.
                                }
                            } else if (BuildConfig.DEBUG) {
                                Log.w(CHERRY_LOG_TAG, "Blocked non-HTTPS navigation")
                            }
                            return true
                        }

                        override fun onPageStarted(view: WebView, url: String?, favicon: Bitmap?) {
                            isLoading = true
                            fatalError = null
                            bridge.onPageStarted()
                            if (BuildConfig.DEBUG) Log.d(CHERRY_LOG_TAG, "page started $url")
                            onCanGoBackChanged(view.canGoBack())
                        }

                        override fun onPageFinished(view: WebView, url: String?) {
                            if (BuildConfig.DEBUG) Log.d(CHERRY_LOG_TAG, "page finished $url")
                            onCanGoBackChanged(view.canGoBack())
                        }

                        override fun onReceivedError(
                            view: WebView,
                            request: WebResourceRequest,
                            error: WebResourceError,
                        ) {
                            if (request.isForMainFrame) {
                                fatalError = "Unable to load chat: ${error.description}"
                                isLoading = false
                                if (BuildConfig.DEBUG) Log.e(CHERRY_LOG_TAG, fatalError!!)
                            }
                        }

                        override fun onReceivedHttpError(
                            view: WebView,
                            request: WebResourceRequest,
                            errorResponse: WebResourceResponse,
                        ) {
                            val url = request.url.toString()
                            if (BuildConfig.DEBUG && url.contains("cherry", ignoreCase = true)) {
                                Log.w(CHERRY_LOG_TAG, "HTTP ${errorResponse.statusCode}: $url")
                            }
                        }
                    }

                    doOnLayout { bridge.sendConfigIfReady() }
                    loadUrl(CHAT_ASSET_URL)
                    onWebViewCreated(this)
                }
            },
            update = {
                bridge.updateToken(token)
            },
        )

        when {
            fatalError != null -> ErrorState(
                message = fatalError!!,
                onRetry = {
                    fatalError = null
                    isLoading = true
                    currentOnReloadRequested()
                },
            )

            isLoading -> LoadingState()
        }
    }
}

private fun cherryErrorMessage(data: Any?): String {
    if (data is JSONObject) {
        return data.optString("message").ifBlank {
            data.optString("code").ifBlank { "Cherry chat reported an error." }
        }
    }
    return data?.toString()?.takeIf { it.isNotBlank() } ?: "Cherry chat reported an error."
}

private class CherryNativeBridge(
    private val onEvent: (String, Any?) -> Unit,
) {
    private var webView: WebView? = null
    private var token: String = ""
    private var hostReady = false

    fun attach(view: WebView) {
        webView = view
    }

    fun detach() {
        webView = null
        hostReady = false
    }

    fun onPageStarted() {
        hostReady = false
    }

    fun updateToken(value: String) {
        token = value
        sendConfigIfReady()
    }

    fun sendConfigIfReady() {
        val view = webView ?: return
        if (!hostReady || view.url != CHAT_ASSET_URL || token.isBlank()) return

        val config = JSONObject()
            .put("appId", CHERRY_APP_ID)
            .put("roomId", CHERRY_ROOM_ID)
            .put("mode", "single")
            .put("embedUrl", CHERRY_EMBED_URL)
            .put("token", token)
            .put(
                "theme",
                JSONObject()
                    .put("mode", "dark")
                    .put("primaryColor", "#FF5BA8"),
            )
            .put(
                "layout",
                JSONObject()
                    .put("showHeader", true)
                    .put("headerTitle", "Seekerthon Chat")
                    .put("showMemberCount", true)
                    .put("showInput", true),
            )

        val script = "window.__cherryReceiveConfig(${JSONObject.quote(config.toString())}); true;"
        view.post {
            if (hostReady && view.url == CHAT_ASSET_URL) {
                view.evaluateJavascript(script, null)
            }
        }
    }

    fun postMessage(sourceView: WebView, payload: String) {
        if (sourceView !== webView) return
        val message = runCatching { JSONObject(payload) }.getOrElse {
            if (BuildConfig.DEBUG) Log.w(CHERRY_LOG_TAG, "Ignored malformed host message")
            return
        }
        val view = webView ?: return

        when (message.optString("type")) {
            "ready" -> view.post {
                if (view.url == CHAT_ASSET_URL) {
                    hostReady = true
                    sendConfigIfReady()
                }
            }

            "event" -> {
                val event = message.optString("event")
                val data = message.opt("data").takeUnless { it == JSONObject.NULL }
                view.post { onEvent(event, data) }
            }
        }
    }
}
