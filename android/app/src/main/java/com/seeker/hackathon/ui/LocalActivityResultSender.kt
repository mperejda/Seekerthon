package com.seeker.hackathon.ui

import androidx.compose.runtime.staticCompositionLocalOf
import com.solana.mobilewalletadapter.clientlib.ActivityResultSender

val LocalActivityResultSender = staticCompositionLocalOf<ActivityResultSender> {
    error("No ActivityResultSender provided — wrap your content with CompositionLocalProvider")
}
