package com.alpinelabs.seekerthon.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val Purple = Color(0xFF7F77DD)
private val PurpleDark = Color(0xFF534AB7)
private val Teal = Color(0xFF1D9E75)
private val Amber = Color(0xFFBA7517)

private val DarkColorScheme = darkColorScheme(
    primary = Purple,
    secondary = Teal,
    tertiary = Amber,
    background = Color(0xFF0A0A12),
    surface = Color(0xFF14141F),
    surfaceVariant = Color(0xFF1E1E2E),
    onBackground = Color.White,
    onSurface = Color.White,
    onSurfaceVariant = Color(0xFFAFA9EC),
)

private val LightColorScheme = lightColorScheme(
    primary = PurpleDark,
    secondary = Teal,
    tertiary = Amber,
    background = Color(0xFFF8F7FF),
    surface = Color.White,
)

@Composable
fun SeekerHackathonTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val colorScheme = if (darkTheme) DarkColorScheme else LightColorScheme
    MaterialTheme(colorScheme = colorScheme, content = content)
}
