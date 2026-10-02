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
 * The "desk" identity as tokens: warm paper, hairline rules instead of shadows, one blue accent, and every figure in
 * tabular monospace. These are the only colour literals in the app; components read [AppTokens] or MaterialTheme.
 * Light and dark follow the phone's own setting.
 */
@Immutable
data class AppTokens(
    val paper: Color,
    val surface: Color,
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
    paper = Color(0xFFF6F1E7), surface = Color(0xFFFBF8F2), ink = Color(0xFF1F1B16), inkMuted = Color(0xFF6B6357),
    rule = Color(0xFFD9D0C1), accent = Color(0xFF1F5FBF), onAccent = Color(0xFFFFFFFF), ok = Color(0xFF2E7D4F),
    warn = Color(0xFF9A6A00), bad = Color(0xFFB3261E),
)

private val Dark = AppTokens(
    paper = Color(0xFF16140F), surface = Color(0xFF1E1B15), ink = Color(0xFFEDE6D8), inkMuted = Color(0xFFA39A8B),
    rule = Color(0xFF3A352C), accent = Color(0xFF7AA7F0), onAccent = Color(0xFF0B1A33), ok = Color(0xFF7BC79A),
    warn = Color(0xFFE0B04F), bad = Color(0xFFF2B8B5),
)

val LocalTokens = staticCompositionLocalOf { Light }

/** Tabular figures: monospace with tnum, so a column of numbers reads as a column. */
val Figures = TextStyle(fontFamily = FontFamily.Monospace, fontFeatureSettings = "tnum", fontSize = 15.sp)
val BigFigure = Figures.copy(fontSize = 44.sp, fontWeight = FontWeight.Medium)

@Composable
fun BioRigTheme(dark: Boolean = isSystemInDarkTheme(), content: @Composable () -> Unit) {
    val t = if (dark) Dark else Light
    val scheme = if (dark) {
        darkColorScheme(primary = t.accent, onPrimary = t.onAccent, background = t.paper, onBackground = t.ink,
            surface = t.surface, onSurface = t.ink, outline = t.rule, error = t.bad)
    } else {
        lightColorScheme(primary = t.accent, onPrimary = t.onAccent, background = t.paper, onBackground = t.ink,
            surface = t.surface, onSurface = t.ink, outline = t.rule, error = t.bad)
    }
    CompositionLocalProvider(LocalTokens provides t) {
        MaterialTheme(colorScheme = scheme, content = content)
    }
}
