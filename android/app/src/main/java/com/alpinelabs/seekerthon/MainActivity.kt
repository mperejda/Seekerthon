package com.alpinelabs.seekerthon

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import com.alpinelabs.seekerthon.ui.AppNavGraph
import com.alpinelabs.seekerthon.ui.LocalActivityResultSender
import com.alpinelabs.seekerthon.ui.theme.SeekerHackathonTheme
import com.solana.mobilewalletadapter.clientlib.ActivityResultSender
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    // Must be created before onStart — constructor calls registerForActivityResult.
    private lateinit var activityResultSender: ActivityResultSender

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        activityResultSender = ActivityResultSender(this)
        enableEdgeToEdge()
        setContent {
            SeekerHackathonTheme {
                CompositionLocalProvider(LocalActivityResultSender provides activityResultSender) {
                    Surface(
                        modifier = Modifier.fillMaxSize(),
                        color = MaterialTheme.colorScheme.background,
                    ) {
                        AppNavGraph()
                    }
                }
            }
        }
    }
}
