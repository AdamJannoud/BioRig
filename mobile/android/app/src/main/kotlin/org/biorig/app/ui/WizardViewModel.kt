package org.biorig.app.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import org.biorig.app.BioRigApp
import org.biorig.app.device.FixSource
import org.biorig.app.device.PhotoKind
import org.biorig.app.device.PhotoStore
import org.biorig.core.RelayDefaults
import org.biorig.core.allometry.Allometry
import org.biorig.core.allometry.Estimate
import org.biorig.core.chain.Eip55
import org.biorig.core.chain.TreeStats
import org.biorig.core.geo.CollisionCheck
import org.biorig.core.geo.CollisionVerdict
import org.biorig.core.geo.Fix
import org.biorig.core.geo.FixVerdict
import org.biorig.core.geo.KnownTree
import org.biorig.core.photo.PhotoCheck
import org.biorig.core.queue.CaptureEntity
import org.biorig.core.queue.CaptureState
import org.biorig.core.relay.RegistrationBuilder
import org.biorig.core.relay.RelayResult
import java.io.File

enum class Screen { SETUP, FIX, PHOTOS, SUBMIT, QUEUE, TREE }

data class ChainView(
    val stats: TreeStats? = null,
    val nullifierActive: Boolean? = null,
    val block: Long? = null,
    val error: String? = null,
    val loading: Boolean = false,
)

data class WizardState(
    val screen: Screen = Screen.SETUP,
    val planterAddress: String? = null,
    val planterError: String? = null,
    // step 1
    val fix: Fix? = null,
    val fixVerdict: FixVerdict? = null,
    val fixLoading: Boolean = false,
    val fixError: String? = null,
    val collision: CollisionVerdict? = null,
    val plotUnavailable: Boolean = false,
    /** Set when step 1 is re-fixing a queued capture the relay refused for its fix. */
    val refixFor: String? = null,
    // step 2
    val submissionId: String = RegistrationBuilder.newSubmissionId(),
    val photos: Map<PhotoKind, String> = emptyMap(),
    val photoVerdict: PhotoCheck.Verdict? = null,
    val photoDigest: String? = null,
    val dbhCm: Int = 10,
    // step 3
    val species: String = RelayDefaults.SPECIES_OPTIONS.first(),
    val speciesOptions: List<String> = RelayDefaults.SPECIES_OPTIONS,
    // later
    val treeId: String? = null,
    val chain: ChainView = ChainView(),
) {
    val estimate: Estimate get() = Allometry.estimate(dbhCm)
    val fixUsable: Boolean get() = fixVerdict is FixVerdict.Usable && collision !is CollisionVerdict.CellFull &&
        collision !is CollisionVerdict.SameTreeAsOwn
    val cell: String? get() = (fixVerdict as? FixVerdict.Usable)?.cell
    val photosReady: Boolean get() = photos.containsKey(PhotoKind.TRUNK) && photoVerdict == PhotoCheck.Verdict.Ok
}

class WizardViewModel(app: Application) : AndroidViewModel(app) {
    private val graph = (app as BioRigApp).graph
    private val fixes = FixSource(app)
    val photoStore = PhotoStore(app)
    private val _state = MutableStateFlow(
        WizardState(
            planterAddress = graph.prefs.planterAddress,
            screen = if (graph.prefs.planterAddress == null) Screen.SETUP else Screen.FIX,
        ),
    )
    val state: StateFlow<WizardState> = _state.asStateFlow()
    val satellites = fixes.satellites
    val captures: StateFlow<List<CaptureEntity>> =
        graph.db.captures().observeAll().stateIn(viewModelScope, SharingStarted.Eagerly, emptyList())

    private fun now() = System.currentTimeMillis() / 1000

    fun go(screen: Screen) = _state.update { it.copy(screen = screen) }

    fun savePlanter(input: String) {
        when (val c = Eip55.validate(input)) {
            is Eip55.Check.Valid -> {
                graph.prefs.planterAddress = c.checksummed
                _state.update { it.copy(planterAddress = c.checksummed, planterError = null, screen = Screen.FIX) }
            }
            is Eip55.Check.Invalid -> _state.update { it.copy(planterError = c.reason) }
        }
    }

    fun startSatellites() = fixes.startSatellites()
    fun stopSatellites() = fixes.stopSatellites()

    /** Step 1: fix, gate, then the pre-check against this phone's own trees and the relay's plot index. */
    fun takeFix() {
        _state.update { it.copy(fixLoading = true, fixError = null) }
        viewModelScope.launch {
            val fix = runCatching { fixes.current() }.getOrNull()
            if (fix == null) {
                _state.update { it.copy(fixLoading = false, fixError = "No position yet. Stay outside and try again.") }
                return@launch
            }
            val verdict = graph.fixGate.judge(fix, now())
            var collision: CollisionVerdict? = null
            var unavailable = false
            if (verdict is FixVerdict.Usable) {
                val refix = _state.value.refixFor
                val own = graph.captures.all()
                    .filter { it.state != CaptureState.DISCARDED && it.submissionId != refix }
                    .map { KnownTree(it.submissionId, it.lat, it.lng) }
                val plot = graph.relay.plot(verdict.cell)
                unavailable = plot !is RelayResult.Ok
                val occ = (plot as? RelayResult.Ok)?.value
                collision = CollisionCheck.judge(fix, own, occ?.active, occ?.full, occ?.neighbourhoodActive,
                    occ?.maxTreesPerCell ?: RelayDefaults.MAX_TREES_PER_CELL,
                    occ?.collisionRadiusM ?: RelayDefaults.COLLISION_RADIUS_M)
            }
            _state.update {
                it.copy(fix = fix, fixVerdict = verdict, collision = collision, plotUnavailable = unavailable, fixLoading = false)
            }
        }
    }

    fun useFix() {
        val s = _state.value
        val fix = s.fix ?: return
        if (!s.fixUsable) return
        val refix = s.refixFor
        if (refix != null) {
            viewModelScope.launch {
                graph.captures.get(refix)?.let { c ->
                    graph.queue.requeue(c.copy(lat = fix.lat, lng = fix.lng, accuracyM = fix.accuracyM, fixCapturedAt = fix.capturedAt))
                }
                graph.flush()
                _state.update { it.copy(refixFor = null, screen = Screen.QUEUE) }
            }
            return
        }
        _state.update { it.copy(screen = Screen.PHOTOS) }
    }

    fun photoFile(kind: PhotoKind): File = photoStore.fileFor(_state.value.submissionId, kind)

    fun photoTaken(kind: PhotoKind, file: File) {
        val fix = _state.value.fix ?: return
        _state.update { s ->
            val photos = s.photos + (kind to file.absolutePath)
            if (kind == PhotoKind.TRUNK) {
                s.copy(photos = photos, photoVerdict = photoStore.check(file, fix), photoDigest = photoStore.digest(file))
            } else s.copy(photos = photos)
        }
    }

    fun setDbh(cm: Int) = _state.update { it.copy(dbhCm = cm.coerceIn(Allometry.DBH_MIN_CM, Allometry.DBH_MAX_CM)) }

    fun setSpecies(species: String) = _state.update { it.copy(species = species) }

    /** Step 3: save the row (the submission id is fixed from here on), then try to send it. */
    fun submit() {
        val s = _state.value
        val fix = s.fix ?: return
        val planter = s.planterAddress ?: return
        viewModelScope.launch {
            graph.captures.upsert(
                CaptureEntity(
                    submissionId = s.submissionId, planterAddress = planter, lat = fix.lat, lng = fix.lng,
                    accuracyM = fix.accuracyM, fixCapturedAt = fix.capturedAt, species = s.species, dbhCm = s.dbhCm,
                    photoSha256 = s.photoDigest, photoPath = s.photos[PhotoKind.TRUNK], createdAt = now(),
                ),
            )
            graph.flush()
            _state.value = WizardState(planterAddress = planter, screen = Screen.QUEUE,
                speciesOptions = s.speciesOptions, species = s.species)
        }
    }

    fun newTree() = _state.update {
        WizardState(planterAddress = it.planterAddress, screen = Screen.FIX, speciesOptions = it.speciesOptions,
            species = it.species)
    }

    fun sendNow() = graph.flush()

    // Acting on a refusal. Each keeps the capture's submission id: no row was created at the relay for a refusal.
    fun refix(id: String) = _state.update { it.copy(refixFor = id, fix = null, fixVerdict = null, collision = null, screen = Screen.FIX) }

    fun remeasure(id: String, dbhCm: Int) = viewModelScope.launch {
        graph.captures.get(id)?.let { graph.queue.requeue(it.copy(dbhCm = dbhCm)) }
        graph.flush()
    }

    /** species_not_allowed: the relay's error.allowed becomes the picker's list from now on. */
    fun chooseAllowedSpecies(id: String, species: String) = viewModelScope.launch {
        graph.captures.get(id)?.let { c ->
            _state.update { it.copy(speciesOptions = c.allowedSpeciesList.ifEmpty { it.speciesOptions }, species = species) }
            graph.queue.requeue(c.copy(species = species))
        }
        graph.flush()
    }

    fun discard(id: String) = viewModelScope.launch {
        graph.captures.get(id)?.let { graph.captures.upsert(it.copy(state = CaptureState.DISCARDED, updatedAt = now())) }
    }

    fun retry(id: String) = viewModelScope.launch {
        graph.captures.get(id)?.let { graph.queue.requeue(it) }
        graph.flush()
    }

    /** Later: the relay's job first, then the contract's own answer over the phone's RPC connection. */
    fun openTree(id: String) {
        _state.update { it.copy(treeId = id, screen = Screen.TREE, chain = ChainView(loading = true)) }
        viewModelScope.launch {
            val c = graph.captures.get(id)?.let { graph.queue.poll(it) } ?: return@launch
            if (c.tokenId == null || c.nullifier == null) {
                _state.update { it.copy(chain = ChainView()) }
                return@launch
            }
            val view = runCatching {
                ChainView(
                    stats = graph.chain.treeStats(c.tokenId!!),
                    nullifierActive = graph.chain.isNullifierActive(c.nullifier!!),
                    block = graph.chain.blockNumber(),
                )
            }.getOrElse { ChainView(error = "The chain did not answer: ${it.message}") }
            _state.update { it.copy(chain = view) }
        }
    }

    fun nullifierConsistent(c: CaptureEntity): Boolean? {
        val cell = c.cell ?: return null
        val ordinal = c.treeOrdinal ?: return null
        val n = c.nullifier ?: return null
        return runCatching { graph.nullifier.forOrdinal(cell, ordinal).nullifierHex == n }.getOrNull()
    }
}

