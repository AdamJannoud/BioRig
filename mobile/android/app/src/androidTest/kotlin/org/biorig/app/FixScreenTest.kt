package org.biorig.app

// UNRUN IN THIS ENVIRONMENT. Compose UI test: needs a device or emulator (`./gradlew :app:connectedDebugAndroidTest`).
// The machine this was written on has no emulator, so this file was compiled at most, never executed.

import android.Manifest
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.rule.GrantPermissionRule
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class FixScreenTest {
    @get:Rule val compose = createEmptyComposeRule()
    @get:Rule val permissions: GrantPermissionRule =
        GrantPermissionRule.grant(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.CAMERA)

    /** With an address saved the app opens on step 1, and before any fix "Use this fix" is disabled. */
    @Test
    fun useFixStartsDisabled() {
        ApplicationProvider.getApplicationContext<BioRigApp>().graph.prefs.planterAddress =
            "0xD314e37FD8538fe66231EE670B74C9428d03feEa"
        ActivityScenario.launch(MainActivity::class.java).use {
            compose.onNodeWithText("Take fix").assertIsDisplayed()
            compose.onNodeWithTag("use_fix").assertIsNotEnabled()
        }
    }

    /** First launch with no address lands on setup, and a mistyped checksum is refused there. */
    @Test
    fun setupRefusesABadChecksum() {
        ApplicationProvider.getApplicationContext<BioRigApp>().graph.prefs.planterAddress = null
        ActivityScenario.launch(MainActivity::class.java).use {
            compose.onNodeWithTag("planter_input").assertIsDisplayed()
        }
    }
}
