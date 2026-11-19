package com.dev.placeexplorer.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/**
 * PlaceExplorer brand theme. Dynamic color is disabled so the app always
 * shows the travel-brand palette regardless of the user's wallpaper.
 *
 * The app always uses the light scheme: every screen sits on the fixed
 * light-blue AppBackgroundBrush, and dark-scheme text/icons (pale blue)
 * would be invisible on it.
 */
@Composable
fun PlaceExplorerTheme(
    darkTheme: Boolean = false,
    content: @Composable () -> Unit
) {
    val colorScheme = if (darkTheme) DarkColorScheme else LightColorScheme
    MaterialTheme(
        colorScheme = colorScheme,
        typography = Typography,
        content = content
    )
}
