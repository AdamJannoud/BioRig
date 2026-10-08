package org.biorig.app

import android.Manifest
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import kotlinx.coroutines.delay
import org.biorig.app.ui.BioRigTheme
import org.biorig.app.ui.FixRoute
import org.biorig.app.ui.PhotosRoute
import org.biorig.app.ui.QueueRoute
import org.biorig.app.ui.Screen
import org.biorig.app.ui.SetupRoute
import org.biorig.app.ui.SubmitRoute
import org.biorig.app.ui.TreeRoute
import org.biorig.app.ui.WizardViewModel

class MainActivity : ComponentActivity() {
    private val vm: WizardViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent { BioRigTheme { App(vm) } }
    }

    override fun onResume() {
        super.onResume()
        (application as BioRigApp).graph.flush()
    }
}

@Composable
fun App(vm: WizardViewModel) {
    val state by vm.state.collectAsState()
    val permissions = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { granted ->
        if (granted[Manifest.permission.ACCESS_FINE_LOCATION] == true) vm.startSatellites()
    }
    LaunchedEffect(Unit) {
        permissions.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.CAMERA))
    }
    DisposableEffect(Unit) { onDispose { runCatching { vm.stopSatellites() } } }
    // Poll jobs in flight every few seconds while the app is open (the contract's polling path: 2-5 s).
    LaunchedEffect(Unit) {
        while (true) {
            delay(4_000)
            vm.sendNow()
        }
    }
    BackHandler(enabled = state.screen != Screen.FIX && state.screen != Screen.SETUP) {
        vm.go(
            when (state.screen) {
                Screen.SUBMIT -> Screen.PHOTOS
                Screen.PHOTOS -> Screen.FIX
                Screen.TREE -> Screen.QUEUE
                else -> Screen.FIX
            },
        )
    }
    Scaffold(Modifier.fillMaxSize()) { pad ->
        androidx.compose.foundation.layout.Box(Modifier.padding(pad)) {
            when (state.screen) {
                Screen.SETUP -> SetupRoute(vm)
                Screen.FIX -> FixRoute(vm)
                Screen.PHOTOS -> PhotosRoute(vm)
                Screen.SUBMIT -> SubmitRoute(vm)
                Screen.QUEUE -> QueueRoute(vm)
                Screen.TREE -> TreeRoute(vm)
            }
        }
    }
}
