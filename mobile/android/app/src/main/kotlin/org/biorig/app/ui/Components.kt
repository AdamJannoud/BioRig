package org.biorig.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable
fun Header(left: String, right: String) {
    val t = LocalTokens.current
    Row(Modifier.fillMaxWidth().padding(vertical = 12.dp), horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically) {
        Text(left, fontWeight = FontWeight.SemiBold, fontSize = 18.sp, color = t.ink)
        Text(right, style = Figures.copy(fontSize = 13.sp), color = t.inkMuted)
    }
    Rule()
}

@Composable
fun Rule() = HorizontalDivider(thickness = 1.dp, color = LocalTokens.current.rule)

/** A label and a figure on one hairline-ruled row. */
@Composable
fun FigureRow(label: String, value: String, mono: Boolean = true) {
    val t = LocalTokens.current
    Row(Modifier.fillMaxWidth().padding(vertical = 9.dp), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, color = t.inkMuted, fontSize = 14.sp)
        Text(value, style = if (mono) Figures else Figures.copy(fontFamily = null), color = t.ink)
    }
    Rule()
}

@Composable
fun Note(text: String) {
    Text(text, color = LocalTokens.current.inkMuted, fontSize = 13.sp, modifier = Modifier.padding(vertical = 8.dp))
}

enum class Tone { OK, WARN, BAD }

@Composable
fun StatusLine(title: String, detail: String?, tone: Tone) {
    val t = LocalTokens.current
    val colour = when (tone) { Tone.OK -> t.ok; Tone.WARN -> t.warn; Tone.BAD -> t.bad }
    Column(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
        Text(title, color = colour, fontWeight = FontWeight.SemiBold)
        if (detail != null) Text(detail, color = t.inkMuted, fontSize = 13.sp)
    }
    Rule()
}

@Composable
fun Primary(text: String, enabled: Boolean = true, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val t = LocalTokens.current
    Button(onClick, enabled = enabled, modifier = modifier.fillMaxWidth().padding(top = 12.dp),
        colors = ButtonDefaults.buttonColors(containerColor = t.accent, contentColor = t.onAccent)) { Text(text) }
}

@Composable
fun Secondary(text: String, modifier: Modifier = Modifier, onClick: () -> Unit) {
    OutlinedButton(onClick, modifier = modifier.padding(top = 8.dp)) { Text(text) }
}

/** Phone-width column, centred on a tablet or a wide window. */
@Composable
fun Page(content: @Composable ColumnScope.() -> Unit) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) {
        Column(Modifier.widthIn(max = 560.dp).fillMaxWidth().padding(horizontal = 20.dp), content = content)
    }
}

@Composable
fun Gap() = Spacer(Modifier.height(8.dp))

fun shortHex(value: String, head: Int = 6, tail: Int = 4): String =
    if (value.length <= head + tail + 1) value else value.take(head) + "…" + value.takeLast(tail)
