package org.biorig.app.ui

import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember

// The ViewModel side of each screen: collect its state, hand the stateless screen in Screens.kt plain values, and turn
// its callbacks into WizardViewModel calls. The camera, the database and the location source stay on this side.

@Composable
fun SetupRoute(vm: WizardViewModel) {
    val state by vm.state.collectAsState()
    SetupScreen(state, vm::savePlanter)
}

@Composable
fun FixRoute(vm: WizardViewModel) {
    val state by vm.state.collectAsState()
    val sats by vm.satellites.collectAsState()
    FixScreen(state, sats, onTakeFix = vm::takeFix, onUseFix = vm::useFix, onQueue = { vm.go(Screen.QUEUE) })
}

@Composable
fun PhotosRoute(vm: WizardViewModel) {
    val state by vm.state.collectAsState()
    PhotosScreen(state, onDbh = { vm.setDbh(it) }, onContinue = { vm.go(Screen.SUBMIT) }) { kind, onError ->
        state.fix?.let { fix -> CameraCapture(kind.label, fix, { vm.photoFile(kind) }, { vm.photoTaken(kind, it) }, onError) }
    }
}

@Composable
fun SubmitRoute(vm: WizardViewModel) {
    val state by vm.state.collectAsState()
    SubmitScreen(state, onSpecies = { vm.setSpecies(it) }, onSubmit = vm::submit)
}

@Composable
fun QueueRoute(vm: WizardViewModel) {
    val captures by vm.captures.collectAsState()
    val actions = remember(vm) {
        QueueActions(
            refix = { vm.refix(it) }, remeasure = { id, dbh -> vm.remeasure(id, dbh) },
            chooseSpecies = { id, s -> vm.chooseAllowedSpecies(id, s) }, discard = { vm.discard(it) },
            changeAddress = { vm.go(Screen.SETUP) }, retry = { vm.retry(it) }, openTree = { vm.openTree(it) },
            sendNow = { vm.sendNow() }, newTree = { vm.newTree() },
        )
    }
    QueueScreen(captures, System.currentTimeMillis() / 1000, actions)
}

@Composable
fun TreeRoute(vm: WizardViewModel) {
    val state by vm.state.collectAsState()
    val captures by vm.captures.collectAsState()
    val c = captures.firstOrNull { it.submissionId == state.treeId }
    TreeScreen(c, state.chain, c?.let(vm::nullifierConsistent), onBack = { vm.go(Screen.QUEUE) })
}
