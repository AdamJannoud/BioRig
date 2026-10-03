package org.biorig.core.relay

import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Response
import java.security.SecureRandom

/**
 * Where the install identifier lives. Synchronous on purpose: it is read from inside an OkHttp interceptor, and the
 * app's implementation is the same SharedPreferences file that holds the session token and the planter's address.
 */
interface InstallIdStore {
    fun loadInstallId(): String?
    fun saveInstallId(id: String)
}

/**
 * A random identifier generated once per install and kept: the relay counts its per-caller limits on it, because
 * every outside caller reaches the relay from the platform edge's one address. 128 random bits as lowercase hex.
 * It is pseudonymous and names nothing but this install; clearing the app's data buys a fresh one, which the relay's
 * whole-relay session ceiling bounds.
 */
class InstallId(private val store: InstallIdStore, private val random: SecureRandom = SecureRandom()) {
    @Volatile private var cached: String? = null

    /** The stored value, or a new one generated and stored now. Never empty, never sent without being kept. */
    fun get(): String = cached ?: synchronized(this) {
        cached ?: (store.loadInstallId()?.takeIf { FORMAT.matches(it) } ?: generate().also(store::saveInstallId))
            .also { cached = it }
    }

    private fun generate(): String =
        ByteArray(16).also(random::nextBytes).joinToString("") { "%02x".format(it.toInt() and 0xff) }

    companion object {
        const val HEADER = "X-BioRig-Install-Id"
        val FORMAT = Regex("^[0-9a-f]{32}$")
    }
}

/** Puts the install id on every request through the client it is installed on, so no call site can forget it. */
class InstallIdInterceptor(private val installId: InstallId) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response =
        chain.proceed(chain.request().newBuilder().header(InstallId.HEADER, installId.get()).build())
}

/** The shared relay client with the install id attached: the one place the header is added. */
fun OkHttpClient.withInstallId(installId: InstallId): OkHttpClient =
    newBuilder().addInterceptor(InstallIdInterceptor(installId)).build()
