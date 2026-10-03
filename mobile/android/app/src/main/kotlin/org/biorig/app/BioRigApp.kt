package org.biorig.app

import android.app.Application
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import com.uber.h3core.H3Core
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.biorig.app.data.AppDatabase
import org.biorig.app.data.Prefs
import org.biorig.app.data.RoomCaptureStore
import org.biorig.core.chain.ChainReader
import org.biorig.core.chain.Nullifier
import org.biorig.core.geo.FixGate
import org.biorig.core.geo.H3Index
import org.biorig.core.queue.SubmissionQueue
import org.biorig.core.relay.InstallId
import org.biorig.core.relay.RelayClient

/** Manual constructor injection: the whole object graph, built once. */
class AppGraph(app: Application) {
    val db = AppDatabase.open(app)
    val prefs = Prefs(app)
    val captures = RoomCaptureStore(db.captures())
    val relay = RelayClient(BuildConfig.RELAY_URL, installId = InstallId(prefs))
    val queue = SubmissionQueue(relay, captures, prefs, { System.currentTimeMillis() / 1000 })
    // jniLibs, not the jar's resource extraction: see extractH3Natives in app/build.gradle.kts
    val h3 = H3Index(H3Core.newSystemInstance())
    val fixGate = FixGate(h3)
    val nullifier = Nullifier(h3)
    val chain = ChainReader(BuildConfig.RPC_URL, BuildConfig.PROXY_ADDRESS)
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val sending = Mutex()

    /** Send what is due and follow what is in flight. Serialised so two triggers never send one capture twice. */
    fun flush() {
        scope.launch {
            sending.withLock {
                runCatching { queue.sendDue() }
                runCatching { queue.pollInFlight() }
            }
        }
    }
}

class BioRigApp : Application() {
    lateinit var graph: AppGraph
        private set

    override fun onCreate() {
        super.onCreate()
        graph = AppGraph(this)
        // Back online: send the queue. The row's submission id makes a resend idempotent at the relay.
        getSystemService(ConnectivityManager::class.java).registerDefaultNetworkCallback(
            object : ConnectivityManager.NetworkCallback() {
                override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
                    if (caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)) graph.flush()
                }
            },
        )
    }
}
