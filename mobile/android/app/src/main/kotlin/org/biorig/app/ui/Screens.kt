package org.biorig.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.FilterChip
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import org.biorig.app.device.PhotoKind
import org.biorig.core.RelayDefaults
import org.biorig.core.allometry.Allometry
import org.biorig.core.geo.CollisionVerdict
import org.biorig.core.geo.FixVerdict
import org.biorig.core.photo.PhotoCheck
import org.biorig.core.queue.CaptureEntity
import org.biorig.core.queue.CaptureState
import org.biorig.core.queue.SubmissionQueue
import org.biorig.core.relay.NextStep
import org.biorig.core.relay.PlanterMessage
import org.biorig.core.relay.PlanterMessages
import org.biorig.core.relay.Refusal
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlin.math.roundToInt

private val clock = DateTimeFormatter.ofPattern("HH:mm:ss · d MMM", Locale.UK).withZone(ZoneId.systemDefault())
private val hhmm = DateTimeFormatter.ofPattern("HH:mm", Locale.UK).withZone(ZoneId.systemDefault())
private fun f1(x: Double) = "%.1f".format(Locale.US, x)

@Composable
fun SetupScreen(state: WizardState, onSave: (String) -> Unit) = Page {
    var input by remember { mutableStateOf(state.planterAddress.orEmpty()) }
    Header("BioRig", "Set up")
    Gap()
    Text("Planter address", color = LocalTokens.current.ink)
    Note("The public address that receives each tree's token. Paste it from your wallet.")
    OutlinedTextField(input, { input = it }, singleLine = true, textStyle = Figures,
        isError = state.planterError != null, modifier = Modifier.fillMaxWidth().testTag("planter_input"),
        supportingText = { state.planterError?.let { Text(it) } })
    StatusLine("No key on this phone", "The relay holds the verifier key and signs the mint. Never paste a private key or recovery phrase here.", Tone.OK)
    Primary("Save address", enabled = input.isNotBlank()) { onSave(input) }
}

@Composable
fun FixScreen(vm: WizardViewModel) {
    val state by vm.state.collectAsState()
    val sats by vm.satellites.collectAsState()
    Page {
        Header("BioRig", sats?.let { "GNSS · $it satellites" } ?: "Step 1 of 3")
        if (state.refixFor != null) Note("New fix for a queued tree: the photo and diameter are kept.")
        val fix = state.fix
        when (val v = state.fixVerdict) {
            null -> Note("Stand at the trunk, under open sky if you can, and take a fix.")
            is FixVerdict.TooCoarse -> {
                Text("${f1(v.accuracyM)} m", style = BigFigure, color = LocalTokens.current.bad, modifier = Modifier.testTag("accuracy"))
                StatusLine("Walk into the open", "The relay needs ${v.maxAccuracyM.roundToInt()} m or better.", Tone.BAD)
            }
            is FixVerdict.Stale -> StatusLine("That fix is too old", "Take a new one.", Tone.BAD)
            FixVerdict.InFuture -> StatusLine("The phone's clock is ahead", "Turn on automatic date and time.", Tone.BAD)
            FixVerdict.NotAPlace -> StatusLine("No usable position", "Take a new fix.", Tone.BAD)
            is FixVerdict.Usable -> {
                Text("${f1(v.fix.accuracyM)} m", style = BigFigure, color = LocalTokens.current.ink, modifier = Modifier.testTag("accuracy"))
                Note("Accuracy — inside the ${RelayDefaults.MAX_ACCURACY_M.roundToInt()} m gate")
                FigureRow("Latitude", "%.6f".format(Locale.US, v.fix.lat))
                FigureRow("Longitude", "%.6f".format(Locale.US, v.fix.lng))
                FigureRow("H3 cell · res 12", v.cell)
                FigureRow("Fixed at", clock.format(Instant.ofEpochSecond(v.fix.capturedAt)), mono = false)
                when (val c = state.collision) {
                    is CollisionVerdict.SameTreeAsOwn -> StatusLine("You already captured this tree",
                        "${c.distanceM.roundToInt()} m from a capture on this phone, inside the ${RelayDefaults.COLLISION_RADIUS_M.roundToInt()} m radius.", Tone.BAD)
                    is CollisionVerdict.CellFull -> StatusLine("This plot is full", "${c.active} of ${c.max} trees are registered here. Pick a tree further away.", Tone.BAD)
                    is CollisionVerdict.NeighbourhoodOccupied -> StatusLine("Registered trees nearby",
                        "${c.neighbourhoodActive} in reach of the ${RelayDefaults.COLLISION_RADIUS_M.roundToInt()} m radius. The relay measures the distance when you submit.", Tone.WARN)
                    CollisionVerdict.Clear -> StatusLine("No registered tree nearby", "Clear of the ${RelayDefaults.COLLISION_RADIUS_M.roundToInt()} m collision radius.", Tone.OK)
                    null -> Unit
                }
                if (state.plotUnavailable) Note("No signal for the plot pre-check; the relay checks again when the tree is sent.")
            }
        }
        state.fixError?.let { StatusLine(it, null, Tone.WARN) }
        Note("The cell is computed on the phone and never sent.")
        Secondary(if (fix == null) "Take fix" else "Take a new fix") { vm.takeFix() }
        Primary("Use this fix", enabled = state.fixUsable && !state.fixLoading, modifier = Modifier.testTag("use_fix")) { vm.useFix() }
        if (state.refixFor == null) Secondary("Queue") { vm.go(Screen.QUEUE) }
    }
}

@Composable
fun PhotosScreen(vm: WizardViewModel) {
    val state by vm.state.collectAsState()
    var kind by remember { mutableStateOf(PhotoKind.TRUNK) }
    var cameraError by remember { mutableStateOf<String?>(null) }
    val fix = state.fix ?: return
    Page {
        Column(Modifier.verticalScroll(rememberScrollState())) {
            Header("BioRig", "${state.photos.size} photos")
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                PhotoKind.entries.forEach { k ->
                    FilterChip(kind == k, { kind = k }, label = { Text(k.label + if (state.photos.containsKey(k)) " ✓" else "") })
                }
            }
            CameraCapture(kind.label, fix, { vm.photoFile(kind) }, { vm.photoTaken(kind, it) }, { cameraError = it })
            cameraError?.let { StatusLine("The camera failed", it, Tone.BAD) }
            when (val p = state.photoVerdict) {
                null -> Note("Photograph the trunk first: its digest goes with the registration.")
                PhotoCheck.Verdict.Ok -> StatusLine("Photo checks out", "Taken at this fix, inside the relay's ${RelayDefaults.FIX_MAX_AGE_S / 60}-minute window.", Tone.OK)
                is PhotoCheck.Verdict.TimeMismatch -> StatusLine("Photo time does not match", "File and EXIF times differ. Retake the trunk photo.", Tone.BAD)
                is PhotoCheck.Verdict.TooFarFromFix -> StatusLine("Photo taken away from the fix", "${f1(p.distanceM)} m from it. Retake at the trunk.", Tone.BAD)
                is PhotoCheck.Verdict.OutsideFixWindow -> StatusLine("Photo too far from the fix in time", "Take a new fix, then the photo.", Tone.BAD)
                PhotoCheck.Verdict.NoExifTime -> StatusLine("The photo has no capture time", "Retake the trunk photo.", Tone.BAD)
            }
            Gap()
            Text("Trunk diameter at breast height", color = LocalTokens.current.ink)
            Slider(state.dbhCm.toFloat(), { vm.setDbh(it.roundToInt()) },
                valueRange = Allometry.DBH_MIN_CM.toFloat()..Allometry.DBH_MAX_CM.toFloat(),
                steps = Allometry.DBH_MAX_CM - Allometry.DBH_MIN_CM - 1, modifier = Modifier.testTag("dbh"))
            val e = state.estimate
            FigureRow("Trunk diameter (DBH)", "${f1(e.dbhCm.toDouble())} cm")
            FigureRow("Height (derived)", "${f1(e.heightM)} m")
            FigureRow("Above-ground biomass", "${f1(e.biomassKg)} kg")
            FigureRow("Carbon · CO₂e", "${f1(e.carbonKg)} · ${f1(e.co2eKg)} kg")
            state.photoDigest?.let { FigureRow("Photo digest", shortHex(it)) }
            Note("Chave et al. 2014: the same model and constants as the relay, so the estimate shown is the one the relay accepts. The photo stays on the phone; the relay is given its SHA-256.")
            Primary("Continue to registration", enabled = state.photosReady) { vm.go(Screen.SUBMIT) }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun SubmitScreen(vm: WizardViewModel) {
    val state by vm.state.collectAsState()
    Page {
        Header("BioRig", "Step 3 of 3")
        FigureRow("Planter address", state.planterAddress?.let { shortHex(it, 10, 4) } ?: "—")
        FigureRow("Species", state.species, mono = false)
        if (state.speciesOptions.size > 1) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                state.speciesOptions.forEach { s -> FilterChip(state.species == s, { vm.setSpecies(s) }, label = { Text(s) }) }
            }
        }
        FigureRow("Submission id", shortHex(state.submissionId, 4, 4))
        FigureRow("Payload", "measurement + fix", mono = false)
        StatusLine("No key on this phone", "The relay holds the verifier key and signs the mint.", Tone.OK)
        Note("The app sends the fix, the measurement and the photo digest. It sends no nullifier, no salt and no cell: the relay derives the plot identity itself.")
        Primary("Submit for verification") { vm.submit() }
        Note("A resubmission that reaches the relay twice is answered with the original job, not a second tree.")
    }
}

private fun messageFor(c: CaptureEntity): PlanterMessage? {
    val code = c.lastErrorCode ?: return null
    if (code == SubmissionQueue.UNREACHABLE) {
        return PlanterMessage("Could not reach the relay", "Tried ${c.attempts} times. Send again when you have signal.", NextStep.RetryLater)
    }
    val detail = buildMap {
        c.distanceM?.let { put("distance_m", JsonPrimitive(it)) }
        c.relayValue?.let { put("relay_value", JsonPrimitive(it)) }
        if (c.allowedSpecies != null) put("allowed", JsonArray(c.allowedSpeciesList.map(::JsonPrimitive)))
    }
    val retry = c.nextAttemptAt?.let { it - System.currentTimeMillis() / 1000 }?.coerceAtLeast(0)
    return PlanterMessages.forRefusal(Refusal(c.lastErrorStatus ?: 0, code, c.lastErrorMessage.orEmpty(), null, JsonObject(detail), retry))
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun QueueScreen(vm: WizardViewModel) {
    val captures by vm.captures.collectAsState()
    val visible = captures.filter { it.state != CaptureState.DISCARDED }
    val waiting = visible.count { it.state == CaptureState.QUEUED }
    Page {
        Column(Modifier.verticalScroll(rememberScrollState())) {
            Header("BioRig", if (waiting > 0) "Queue $waiting" else "Up to date")
            if (visible.isEmpty()) Note("No trees captured yet.")
            visible.forEachIndexed { i, c ->
                val n = visible.size - i
                val captured = hhmm.format(Instant.ofEpochSecond(c.createdAt))
                when (c.state) {
                    CaptureState.QUEUED -> StatusLine("Tree $n · waiting to send",
                        "captured $captured · attempt ${c.attempts + 1} of ${RelayDefaults.MAX_SEND_ATTEMPTS}" +
                            (messageFor(c)?.takeIf { c.lastErrorCode == "rate_limited" }?.let { " · ${it.body}" } ?: ""), Tone.WARN)
                    CaptureState.SENT -> StatusLine("Tree $n · ${c.jobState ?: "submitted"}",
                        "captured $captured · " + when (c.outcome) {
                            "same_tree" -> "the relay already had this tree"
                            "replayed" -> "the relay answered with the original job"
                            "recovered" -> "recovered from the chain"
                            else -> "with the relay"
                        }, Tone.WARN)
                    CaptureState.MINTED -> StatusLine("Tree $n · minted token #${c.tokenId}", c.txHash?.let { shortHex(it) }, Tone.OK)
                    CaptureState.REJECTED -> StatusLine("Tree $n · rejected by the relay", "It will not be minted.", Tone.BAD)
                    CaptureState.NEEDS_ATTENTION -> {
                        val m = messageFor(c)
                        StatusLine(m?.title ?: "Needs attention", m?.body, Tone.BAD)
                        when (val next = m?.next) {
                            NextStep.Refix -> Secondary("Take a new fix") { vm.refix(c.submissionId) }
                            NextStep.Remeasure -> RemeasureRow(c) { vm.remeasure(c.submissionId, it) }
                            is NextStep.ChooseSpecies -> FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                next.allowed.forEach { s -> FilterChip(false, { vm.chooseAllowedSpecies(c.submissionId, s) }, label = { Text(s) }) }
                            }
                            NextStep.PickAnotherTree -> Secondary("Remove from the queue") { vm.discard(c.submissionId) }
                            NextStep.FixAddress -> Secondary("Change planter address") { vm.go(Screen.SETUP) }
                            NextStep.RetryLater -> Secondary("Send again") { vm.retry(c.submissionId) }
                            NextStep.UpdateApp, is NextStep.Wait, null -> Unit
                        }
                    }
                }
                if (c.jobId != null) Secondary("Open tree $n") { vm.openTree(c.submissionId) }
            }
            Note("Nothing is lost by closing the app: the queue lives in the phone's database. A queued tree must reach the relay within ${RelayDefaults.FIX_MAX_AGE_S / 60} minutes of its fix, or it asks for a new fix at the tree.")
            Primary(if (waiting > 0) "$waiting waiting · send now" else "Check for updates") { vm.sendNow() }
            Secondary("Capture another tree") { vm.newTree() }
        }
    }
}

@Composable
private fun RemeasureRow(c: CaptureEntity, onSend: (Int) -> Unit) {
    var dbh by remember { mutableIntStateOf(c.dbhCm) }
    Slider(dbh.toFloat(), { dbh = it.roundToInt() }, valueRange = Allometry.DBH_MIN_CM.toFloat()..Allometry.DBH_MAX_CM.toFloat())
    Secondary("Send with $dbh cm") { onSend(dbh) }
}

@Composable
fun TreeScreen(vm: WizardViewModel) {
    val state by vm.state.collectAsState()
    val captures by vm.captures.collectAsState()
    val c = captures.firstOrNull { it.submissionId == state.treeId } ?: return
    Page {
        Column(Modifier.verticalScroll(rememberScrollState())) {
            Header("BioRig", if (c.state == CaptureState.MINTED) "Verified" else (c.jobState ?: c.state))
            FigureRow("Position", "%.6f, %.6f".format(Locale.US, c.lat, c.lng))
            FigureRow("Job", c.jobId?.let { shortHex(it) } ?: "—")
            FigureRow("Relay state", c.jobState ?: "—", mono = false)
            c.tokenId?.let { FigureRow("Token", "#$it") }
            when (vm.nullifierConsistent(c)) {
                true -> StatusLine("Plot identity checks out", "The relay's nullifier is keccak256(cell ‖ salt) for this tree's cell and ordinal.", Tone.OK)
                false -> StatusLine("Plot identity does not match", "The relay's nullifier is not what its cell and ordinal derive to.", Tone.BAD)
                null -> Unit
            }
            val ch = state.chain
            when {
                ch.loading -> Note("Reading the contract…")
                ch.error != null -> StatusLine("Chain not readable yet", ch.error, Tone.WARN)
                ch.stats != null -> {
                    FigureRow("Biomass on chain", "${ch.stats.biomass} kg")
                    FigureRow("Token-bound account", shortHex(ch.stats.tbaAddress, 10, 5))
                    FigureRow("Nullifier", if (ch.nullifierActive == true) "active" else "not active", mono = false)
                    ch.block?.let { FigureRow("Read at block", "%,d".format(Locale.US, it)) }
                }
                else -> Note("The contract is read once the relay reports the mint.")
            }
            Note("Read over the phone's own RPC connection. An empty answer from a public node is asked again before it is believed. The coordinates are not on chain.")
            Secondary("Back to the queue") { vm.go(Screen.QUEUE) }
        }
    }
}
