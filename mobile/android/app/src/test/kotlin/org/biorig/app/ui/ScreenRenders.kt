package org.biorig.app.ui

import android.app.Application
import android.graphics.Bitmap
import android.graphics.Canvas
import androidx.compose.runtime.Composable
import androidx.activity.ComponentActivity
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import org.biorig.app.device.PhotoKind
import org.biorig.core.RelayDefaults
import org.biorig.core.chain.TreeStats
import org.biorig.core.geo.Fix
import org.biorig.core.geo.FixVerdict
import org.biorig.core.photo.PhotoCheck
import org.biorig.core.queue.CaptureEntity
import org.biorig.core.queue.CaptureState
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.ParameterizedRobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File
import java.math.BigInteger

/**
 * Draws each of the six screens, light and dark, from a fixed state and writes it as a PNG. Run through
 * `./gradlew :app:renderScreens`, which passes the output directory and writes manifest.json; the plain unit-test task
 * leaves this class out. The states mirror the phones on the plan page (.bolter/plans/10), with the figures the code
 * actually derives: the accuracy gate is RelayDefaults.MAX_ACCURACY_M, the estimate comes from Allometry.
 *
 * Device spec: 360 x 780 dp at xxhdpi (density 3.0) -> 1080 x 2340 px. Everything that could vary between runs is
 * pinned: the states (no clock, no random submission id), the timezone (UTC, set by the task) and the encoder (Skia's PNG
 * encoder, which writes no timestamp chunk).
 */
@RunWith(ParameterizedRobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
// A plain Application: the screens need nothing from BioRigApp's graph (H3 natives, Room, the relay client).
@Config(sdk = [35], qualifiers = "w360dp-h780dp-xxhdpi", application = Application::class)
class ScreenRenders(private val screen: String, private val mode: String) {
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>()

    @Test
    fun render() {
        val dir = System.getProperty("biorig.renders.dir")
        assumeTrue("run through :app:renderScreens", dir != null)
        compose.setContent { BioRigTheme(darkTheme = mode == "dark") { Draw(screen) } }
        compose.waitForIdle()
        // compose.onRoot().captureToImage() waits for a frame-commit callback Robolectric never delivers (it times out
        // in forceRedraw, software or hardware render mode), so the laid-out window is drawn onto a Skia canvas here.
        val view = compose.activity.window.decorView
        val bitmap = Bitmap.createBitmap(view.width, view.height, Bitmap.Config.ARGB_8888)
        compose.runOnUiThread { view.draw(Canvas(bitmap)) }
        File(dir, "$screen-$mode.png").outputStream().use { out ->
            check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, out)) { "the PNG encoder refused $screen-$mode" }
        }
    }

    companion object {
        @JvmStatic
        @ParameterizedRobolectricTestRunner.Parameters(name = "{0}-{1}")
        fun renders(): List<Array<String>> =
            listOf("setup", "fix", "photos", "submit", "queue", "tree").flatMap { s -> listOf("light", "dark").map { arrayOf(s, it) } }

        // 4 October 2026, 09:41 UTC: the plan's status-bar time.
        private const val T0 = 1_791_106_860L
        private const val PLANTER = "0x3f9a5Be2D0c47A8e1F6b9C3d2E7a4B8c0D5e1c02"
        private const val SUBMISSION = "b4d70f3c2a9e4b1d8c6f5a3e2d1c9e11"
        private val FIX = Fix(24.713600, 46.675300, 4.2, T0)
        private val PHOTO_FIX = WizardState(screen = Screen.PHOTOS, planterAddress = PLANTER, fix = FIX,
            fixVerdict = FixVerdict.Usable(FIX, "8c2a10728b6e3ff"), submissionId = SUBMISSION,
            photos = mapOf(PhotoKind.TRUNK to "trunk.jpg", PhotoKind.CANOPY to "canopy.jpg"),
            photoVerdict = PhotoCheck.Verdict.Ok, dbhCm = 21)

        private fun capture(n: Int, minutes: Long) = CaptureEntity(
            submissionId = "tree$n", planterAddress = PLANTER, lat = FIX.lat, lng = FIX.lng, accuracyM = FIX.accuracyM,
            fixCapturedAt = T0 + minutes * 60, species = "Acacia", dbhCm = 21, photoSha256 = null, photoPath = null,
            createdAt = T0 + minutes * 60,
        )

        private val MINTED = capture(1, 0).copy(state = CaptureState.MINTED, jobId = "4e0b9c7a51d2f388", jobState = "minted",
            tokenId = 7, txHash = "0x8c21d6a9e04b7f13c5a28e9d0b6f4c71a3e95d2b08f6c4a1e7d3b9025c8af04e", cell = "8c2a10728b6e3ff",
            treeOrdinal = 0, nullifier = "0xb7a55a6b1b7e4fe0fba76f303772cba7fdf3715d4030e3fcd91ed297c756d741")
        private val QUEUE = listOf(
            capture(3, 59).copy(state = CaptureState.REJECTED),
            capture(2, 31),
            MINTED,
        )
        private val CHAIN = ChainView(
            stats = TreeStats(BigInteger.valueOf(21), BigInteger.valueOf(148), T0, "0x453e89520DB8f374CFCeA95625B99DF5d4F1256A",
                true, MINTED.nullifier!!),
            nullifierActive = true, block = 78_914_730,
        )
        private val INERT = QueueActions({}, { _, _ -> }, { _, _ -> }, {}, {}, {}, {}, {}, {})
    }

    @Composable
    private fun Draw(name: String) = when (name) {
        "setup" -> SetupScreen(WizardState(screen = Screen.SETUP)) {}
        "fix" -> {
            val coarse = FIX.copy(accuracyM = 38.4)
            FixScreen(WizardState(screen = Screen.FIX, planterAddress = PLANTER, fix = coarse,
                fixVerdict = FixVerdict.TooCoarse(coarse.accuracyM, RelayDefaults.MAX_ACCURACY_M)), null, {}, {}, {})
        }
        "photos" -> PhotosScreen(PHOTO_FIX, {}, {}) { kind, _ -> CameraFrame(kind.label) }
        "submit" -> SubmitScreen(PHOTO_FIX.copy(screen = Screen.SUBMIT, speciesOptions = listOf("Acacia", "Eucalyptus"),
            species = "Acacia"), {}, {})
        "queue" -> QueueScreen(QUEUE, T0 + 3_600, INERT)
        "tree" -> TreeScreen(MINTED, CHAIN, nullifierConsistent = true) {}
        else -> error("no screen $name")
    }
}
