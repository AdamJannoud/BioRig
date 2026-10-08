package org.biorig.app.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

/**
 * The Direction B identity as tokens: deep forest paper, hairline rules instead of shadows, one lime accent with gold
 * and green status colours, and every figure in tabular monospace. These are the only colour literals in the app;
 * components read [AppTokens] or MaterialTheme. Light and dark follow the phone's own setting.
 */
@Immutable
data class AppTokens(
    val paper: Color,
    val surface: Color,
    val surface2: Color,
    val ink: Color,
    val inkMuted: Color,
    val rule: Color,
    val accent: Color,
    val onAccent: Color,
    val ok: Color,
    val warn: Color,
    val bad: Color,
)

private val Light = AppTokens(
    paper = Color(0xFFF6F8F4), surface = Color(0xFFFFFFFF), surface2 = Color(0xFFEFF4EE),
    ink = Color(0xFF0B1F16), inkMuted = Color(0xFF586B60), rule = Color(0xFFDCE7DD),
    accent = Color(0xFF0A5B3A), onAccent = Color(0xFFFFFFFF), ok = Color(0xFF1F7A3D),
    warn = Color(0xFF8A6D00), bad = Color(0xFFB42318),
)

private val Dark = AppTokens(
    paper = Color(0xFF0B1F16), surface = Color(0xFF0D281A), surface2 = Color(0xFF12301F),
    ink = Color(0xFFEAF4EC), inkMuted = Color(0xFF9DB4A6), rule = Color(0xFF1F3D2A),
    accent = Color(0xFF35D07F), onAccent = Color(0xFF04120C), ok = Color(0xFF8FE0AC),
    warn = Color(0xFFE8C547), bad = Color(0xFFF87171),
)

val LocalTokens = staticCompositionLocalOf { Light }

/** Tabular figures: monospace with tnum, so a column of numbers reads as a column. */
val Figures = TextStyle(fontFamily = FontFamily.Monospace, fontFeatureSettings = "tnum", fontSize = 15.sp)
val BigFigure = Figures.copy(fontSize = 44.sp, fontWeight = FontWeight.Medium)

@Composable
fun BioRigTheme(dark: Boolean = isSystemInDarkTheme(), content: @Composable () -> Unit) {
    val t = if (dark) Dark else Light
    val scheme = if (dark) {
        darkColorScheme(
            primary = t.accent, onPrimary = t.onAccent,
            secondaryContainer = t.accent, onSecondaryContainer = t.onAccent,
            background = t.paper, onBackground = t.ink,
            surface = t.paper, onSurface = t.ink,
            surfaceVariant = t.surface2, onSurfaceVariant = t.inkMuted,
            outline = t.rule, outlineVariant = t.rule,
            error = t.bad,
        )
    } else {
        lightColorScheme(
            primary = t.accent, onPrimary = t.onAccent,
            secondaryContainer = t.accent, onSecondaryContainer = t.onAccent,
            background = t.paper, onBackground = t.ink,
            surface = t.paper, onSurface = t.ink,
            surfaceVariant = t.surface2, onSurfaceVariant = t.inkMuted,
            outline = t.rule, outlineVariant = t.rule,
            error = t.bad,
        )
    }
    CompositionLocalProvider(LocalTokens provides t) {
        MaterialTheme(colorScheme = scheme, content = content)
    }
}
