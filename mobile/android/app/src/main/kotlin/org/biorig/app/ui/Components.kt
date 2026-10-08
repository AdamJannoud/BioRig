package org.biorig.app.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

private val Field = RoundedCornerShape(10.dp)
private val ButtonShape = RoundedCornerShape(12.dp)

@Composable
fun Header(left: String, right: String) {
    val t = LocalTokens.current
    Row(Modifier.fillMaxWidth().padding(top = 14.dp, bottom = 12.dp), horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.Bottom) {
        Text(left, fontWeight = FontWeight.Bold, fontSize = 20.sp, letterSpacing = (-0.2).sp, color = t.ink)
        Text(right, style = Figures.copy(fontSize = 13.sp, fontWeight = FontWeight.Medium), color = t.inkMuted)
    }
    Rule()
}

@Composable
fun Rule() = HorizontalDivider(thickness = 1.dp, color = LocalTokens.current.rule)

/** A field's label: the strongest text on a form screen after the header. */
@Composable
fun Label(text: String) {
    Text(text, color = LocalTokens.current.ink, fontSize = 15.sp, fontWeight = FontWeight.SemiBold,
        modifier = Modifier.padding(top = 16.dp, bottom = 2.dp))
}

/** A label and a figure on one hairline-ruled row. */
@Composable
fun FigureRow(label: String, value: String, mono: Boolean = true) {
    val t = LocalTokens.current
    Row(Modifier.fillMaxWidth().padding(vertical = 10.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(label, color = t.inkMuted, fontSize = 14.sp, modifier = Modifier.weight(1f).alignByBaseline())
        Text(value, style = if (mono) Figures else Figures.copy(fontFamily = null), color = t.ink, textAlign = TextAlign.End,
            modifier = Modifier.alignByBaseline())
    }
    Rule()
}

@Composable
fun Note(text: String) {
    Text(text, color = LocalTokens.current.inkMuted, fontSize = 13.sp, lineHeight = 19.sp,
        modifier = Modifier.padding(vertical = 8.dp))
}

enum class Tone { OK, WARN, BAD }

/** A state, coloured by tone: a dot, the verdict in the tone's colour, and what it means in muted text. */
@Composable
fun StatusLine(title: String, detail: String?, tone: Tone) {
    val t = LocalTokens.current
    val colour = when (tone) { Tone.OK -> t.ok; Tone.WARN -> t.warn; Tone.BAD -> t.bad }
    Row(Modifier.fillMaxWidth().padding(vertical = 10.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Box(Modifier.padding(top = 6.dp).size(9.dp).background(colour, CircleShape))
        Column {
            Text(title, color = colour, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
            if (detail != null) Text(detail, color = t.inkMuted, fontSize = 13.sp, lineHeight = 18.sp)
        }
    }
    Rule()
}

@Composable
fun Primary(text: String, enabled: Boolean = true, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val t = LocalTokens.current
    Button(onClick, enabled = enabled, shape = ButtonShape,
        modifier = modifier.fillMaxWidth().padding(top = 12.dp).heightIn(min = 50.dp),
        colors = ButtonDefaults.buttonColors(containerColor = t.accent, contentColor = t.onAccent,
            disabledContainerColor = t.accent.copy(alpha = 0.4f), disabledContentColor = t.onAccent.copy(alpha = 0.85f)),
    ) { Text(text) }
}

@Composable
fun Secondary(text: String, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val t = LocalTokens.current
    OutlinedButton(onClick, shape = ButtonShape, border = BorderStroke(1.dp, t.rule),
        colors = ButtonDefaults.outlinedButtonColors(contentColor = t.ink),
        modifier = modifier.fillMaxWidth().padding(top = 10.dp).heightIn(min = 50.dp)) { Text(text) }
}

/** One choice of several, as a pill: filled with the accent when chosen. */
@Composable
fun Chip(text: String, selected: Boolean, onClick: () -> Unit) {
    val t = LocalTokens.current
    val shape = RoundedCornerShape(999.dp)
    val base = if (selected) Modifier.background(t.accent, shape) else Modifier.border(1.dp, t.rule, shape)
    Box(base.heightIn(min = 36.dp).clip(shape).clickable(onClick = onClick).padding(horizontal = 14.dp), contentAlignment = Alignment.Center) {
        Text(text, fontSize = 13.sp, color = if (selected) t.onAccent else t.inkMuted,
            fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal)
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ChipRow(content: @Composable () -> Unit) {
    FlowRow(Modifier.fillMaxWidth().padding(vertical = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)) { content() }
}

/** The plan's slider: an accent fill on a hairline track and a round knob, with no tick marks or stop dot. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FigureSlider(value: Float, onChange: (Float) -> Unit, range: ClosedFloatingPointRange<Float>, steps: Int,
                 modifier: Modifier = Modifier) {
    val t = LocalTokens.current
    val colors = SliderDefaults.colors(thumbColor = t.accent, activeTrackColor = t.accent, inactiveTrackColor = t.rule,
        activeTickColor = Color.Transparent, inactiveTickColor = Color.Transparent)
    Slider(value, onChange, valueRange = range, steps = steps, modifier = modifier.fillMaxWidth(), colors = colors,
        thumb = { Box(Modifier.size(22.dp).background(t.surface, CircleShape).border(2.dp, t.accent, CircleShape)) },
        track = { state ->
            SliderDefaults.Track(state, Modifier.height(5.dp), colors = colors, drawStopIndicator = null,
                thumbTrackGapSize = 0.dp)
        })
}

@Composable
fun fieldColors() = LocalTokens.current.let { t ->
    OutlinedTextFieldDefaults.colors(focusedContainerColor = t.surface, unfocusedContainerColor = t.surface,
        errorContainerColor = t.surface, focusedBorderColor = t.accent, unfocusedBorderColor = t.rule,
        focusedTextColor = t.ink, unfocusedTextColor = t.ink, cursorColor = t.accent,
        focusedPlaceholderColor = t.inkMuted, unfocusedPlaceholderColor = t.inkMuted, errorBorderColor = t.bad,
        errorSupportingTextColor = t.bad)
}

val FieldShape get() = Field

/**
 * The frame the camera preview sits in, drawn without a camera: a dashed, quiet panel naming the photo to take.
 * PhotosScreen takes its camera as a slot; the app fills it with [CameraCapture], previews and renders with this.
 */
@Composable
fun CameraFrame(label: String) {
    val t = LocalTokens.current
    Box(Modifier.fillMaxWidth().padding(vertical = 8.dp).height(180.dp)
        .background(t.surface2, RoundedCornerShape(14.dp))
        .drawBehind {
            drawRoundRect(t.rule, cornerRadius = CornerRadius(14.dp.toPx()),
                style = Stroke(width = 1.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(6.dp.toPx(), 5.dp.toPx()))))
        }, contentAlignment = Alignment.Center) {
        Text("Photo of the $label", color = t.inkMuted, fontSize = 13.sp)
    }
}

/** Phone-width scrolling column on the app's paper, centred on a tablet or a wide window. */
@Composable
fun Page(content: @Composable ColumnScope.() -> Unit) {
    Row(Modifier.fillMaxSize().background(LocalTokens.current.paper), horizontalArrangement = Arrangement.Center) {
        Column(Modifier.widthIn(max = 560.dp).fillMaxWidth().verticalScroll(rememberScrollState())
            .padding(start = 20.dp, end = 20.dp, bottom = 24.dp), content = content)
    }
}

@Composable
fun Gap() = Spacer(Modifier.height(8.dp))

fun shortHex(value: String, head: Int = 6, tail: Int = 4): String =
    if (value.length <= head + tail + 1) value else value.take(head) + "…" + value.takeLast(tail)
