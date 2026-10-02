package org.biorig.core.queue

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * One captured tree, one row, one registration. The row is written when the planter finishes step 2, before any
 * network call, so closing the app loses nothing; [submissionId] is minted then and never changes, which is what
 * makes a resend idempotent at the relay.
 *
 * Declared here with Room's annotations (room-common is a plain JVM artefact) so the queue logic is testable on the
 * JVM; :app's Room database is generated from this class.
 */
@Entity(tableName = "captures")
data class CaptureEntity(
    @PrimaryKey val submissionId: String,
    val planterAddress: String,
    val lat: Double,
    val lng: Double,
    val accuracyM: Double,
    /** Unix seconds. The relay refuses a fix older than FIX_MAX_AGE_S (600 s) at the moment it arrives. */
    val fixCapturedAt: Long,
    val species: String,
    val dbhCm: Int,
    val photoSha256: String?,
    /** Local file path of the trunk photo. Stays on the phone; only the digest is sent. */
    val photoPath: String?,
    val createdAt: Long,
    val state: String = CaptureState.QUEUED,
    /** Transient failures so far (no answer, 5xx). Reset when the planter acts on a refusal. */
    val attempts: Int = 0,
    val nextAttemptAt: Long? = null,
    val jobId: String? = null,
    val jobState: String? = null,
    val outcome: String? = null,
    val lastErrorCode: String? = null,
    val lastErrorStatus: Int? = null,
    val lastErrorMessage: String? = null,
    /** Comma-joined `error.allowed` from a species_not_allowed refusal. */
    val allowedSpecies: String? = null,
    val distanceM: Double? = null,
    val relayValue: Double? = null,
    val cell: String? = null,
    val treeOrdinal: Int? = null,
    val nullifier: String? = null,
    val tokenId: Long? = null,
    val tba: String? = null,
    val txHash: String? = null,
    val mintBlock: Long? = null,
    val mintBiomassKg: Long? = null,
    val updatedAt: Long = createdAt,
) {
    val allowedSpeciesList: List<String>
        get() = allowedSpecies?.split(',')?.map { it.trim() }?.filter { it.isNotEmpty() }.orEmpty()
}

object CaptureState {
    /** Saved, not yet accepted by the relay. */
    const val QUEUED = "queued"
    /** The relay holds a job for it; polled until minted or rejected. */
    const val SENT = "sent"
    const val MINTED = "minted"
    /** The relay's job ended rejected (job.last_error_code says why). */
    const val REJECTED = "rejected"
    /** Refused, or out of attempts: the planter has to act before it is sent again. */
    const val NEEDS_ATTENTION = "needs_attention"
    /** The planter gave up on it (the plot is taken, the area excluded). Kept as a record, never sent. */
    const val DISCARDED = "discarded"
}

/** Persistence for the queue; :app implements it with Room, the tests with a map. */
interface CaptureStore {
    suspend fun upsert(capture: CaptureEntity)
    suspend fun get(submissionId: String): CaptureEntity?
    suspend fun all(): List<CaptureEntity>
}

data class Session(val token: String, val expiresAt: Long)

/** Where the current session token lives. It is a rate-limit key, not an identity and not a wallet secret. */
interface SessionStore {
    suspend fun load(): Session?
    suspend fun save(session: Session?)
}
