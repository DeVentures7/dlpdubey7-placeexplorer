package com.dev.placeexplorer.ui.theme

import androidx.compose.ui.graphics.Color

/**
 * Brand palette: a blue family throughout. Very light blue backgrounds,
 * darker blue actions and tiles; slate text keeps the contrast quiet and
 * professional. Tailwind-scale blue/slate tones for consistency.
 */

// Brand anchors
val BrandBlue = Color(0xFF1D4ED8)        // blue-700 — primary actions
val BrandBlueDeep = Color(0xFF1E3A8A)    // blue-900 — header gradient
val BrandBlueBright = Color(0xFF60A5FA)  // blue-400 — dark-mode primary
val BrandSky = Color(0xFF0284C7)         // sky-600 — secondary emphasis

val LightColorScheme = androidx.compose.material3.lightColorScheme(
    primary = BrandBlue,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFDBEAFE),   // blue-100 — selected tiles
    onPrimaryContainer = Color(0xFF172554), // blue-950
    secondary = BrandSky,
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFE0F2FE), // sky-100
    onSecondaryContainer = Color(0xFF0C4A6E),
    tertiary = Color(0xFF1E40AF),           // blue-800 — highlights
    onTertiary = Color.White,
    tertiaryContainer = Color(0xFFDBEAFE),
    onTertiaryContainer = Color(0xFF172554),
    background = Color(0xFFEFF6FF),         // blue-50 — very light blue app background
    onBackground = Color(0xFF0F172A),
    surface = Color.White,                  // cards stay white for contrast
    onSurface = Color(0xFF0F172A),
    surfaceVariant = Color(0xFFE0EAFA),     // light blue tile resting color
    onSurfaceVariant = Color(0xFF334155),
    outline = Color(0xFF93B4E8),            // soft blue outline
    outlineVariant = Color(0xFFDBEAFE),
    error = Color(0xFFB91C1C),
    onError = Color.White,
    errorContainer = Color(0xFFFEE2E2),
    onErrorContainer = Color(0xFF7F1D1D)
)

val DarkColorScheme = androidx.compose.material3.darkColorScheme(
    primary = BrandBlueBright,
    onPrimary = Color(0xFF0B1E4B),
    primaryContainer = Color(0xFF1E40AF),
    onPrimaryContainer = Color(0xFFDBEAFE),
    secondary = Color(0xFF7DD3FC),          // sky-300
    onSecondary = Color(0xFF0C4A6E),
    secondaryContainer = Color(0xFF164E63),
    onSecondaryContainer = Color(0xFFE0F2FE),
    tertiary = Color(0xFF93C5FD),           // blue-300
    onTertiary = Color(0xFF172554),
    tertiaryContainer = Color(0xFF1E3A8A),
    onTertiaryContainer = Color(0xFFDBEAFE),
    background = Color(0xFF0A1220),
    onBackground = Color(0xFFDBEAFE),
    surface = Color(0xFF101B30),
    onSurface = Color(0xFFDBEAFE),
    surfaceVariant = Color(0xFF1B2B4A),
    onSurfaceVariant = Color(0xFF93B4E8),
    outline = Color(0xFF33507E),
    outlineVariant = Color(0xFF223A5E),
    error = Color(0xFFF87171),
    onError = Color(0xFF7F1D1D),
    errorContainer = Color(0xFF7F1D1D),
    onErrorContainer = Color(0xFFFEE2E2)
)
