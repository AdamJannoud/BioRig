package org.biorig.core.queue

import org.biorig.core.RelayDefaults
import org.biorig.core.relay.Job
import org.biorig.core.relay.NextStep
import org.biorig.core.relay.PlanterMessages
import org.biorig.core.relay.Refusal
import org.biorig.core.relay.RegistrationBuilder
import org.biorig.core.relay.RegistrationResponse
import org.biorig.core.relay.RelayClient
import org.biorig.core.relay.RelayResult

/**
 * Sends saved captures to the relay and follows their jobs. Every decision here is driven by a documented response:
 *
 * - 202 created, 200 replayed / same_tree / recovered: the capture now has a job and is polled.
 * - session_required / session_invalid / session_expired, or rate_limited on `per_session`: open a new session and
 *   send again once. The submission id is unchanged, so a capture that did reach the relay under the old session
 *   comes back as `same_tree` (same planter within the collision radius), not as a second tree.
 * - rate_limited on any other limit: wait the relay's Retry-After; not counted as a failed attempt.
 * - no answer, or a 5xx: counted against [maxAttempts] with backoff, then the planter is asked.
 * - any other refusal: the planter is asked, with the sentence and the single next step from [PlanterMessages].
 *
 * A fix older than the relay's FIX_MAX_AGE_S is not sent at all (the relay would refuse it with fix_stale and count
 * the attempt against the IP limit); it goes straight to the planter as a re-fix.
 */
class SubmissionQueue(
    private val client: RelayClient,
    private val captures: CaptureStore,
    private val sessions: SessionStore,
    private val clock: () -> Long,
    private val maxAttempts: Int = RelayDefaults.MAX_SEND_ATTEMPTS,
    private val backoffS: List<Long> = listOf(30, 120, 600),
) {
    /** Captures waiting to be sent whose next attempt is due. */
    suspend fun due(): List<CaptureEntity> {
        val now = clock()
        return captures.all().filter { it.state == CaptureState.QUEUED && (it.nextAttemptAt ?: 0) <= now }
            .sortedBy { it.createdAt }
    }

    suspend fun sendDue(): List<CaptureEntity> = due().map { send(it) }

    /** Follow every capture whose job is still in flight. */
    suspend fun pollInFlight(): List<CaptureEntity> =
        captures.all().filter { it.state == CaptureState.SENT && it.jobId != null }.map { poll(it) }

    suspend fun send(capture: CaptureEntity): CaptureEntity {
        val now = clock()
        if (capture.fixCapturedAt < now - RelayDefaults.FIX_MAX_AGE_S) {
            return save(
                capture.copy(
                    state = CaptureState.NEEDS_ATTENTION, lastErrorCode = "fix_stale", lastErrorStatus = null,
                    lastErrorMessage = "the fix is older than ${RelayDefaults.FIX_MAX_AGE_S} s; not sent",
                    nextAttemptAt = null, updatedAt = now,
                ),
            )
        }
        val request = RegistrationBuilder.build(capture)
        var renewed = false
        while (true) {
            val session = currentSession() ?: return transientFailure(capture, null, sessionRefusal = lastSessionRefusal)
            when (val result = client.submit(session.token, request)) {
                is RelayResult.Ok -> return accepted(capture, result.value)
                is RelayResult.Unreachable -> return transientFailure(capture, null)
                is RelayResult.Refused -> {
                    val r = result.refusal
                    val sessionProblem = r.code in SESSION_CODES || (r.code == "rate_limited" && r.limit == "per_session")
                    if (sessionProblem && !renewed) {
                        sessions.save(null)
                        renewed = true
                        continue
                    }
                    return refused(capture, r)
                }
            }
        }
    }

    suspend fun poll(capture: CaptureEntity): CaptureEntity {
        val id = capture.jobId ?: return capture
        return when (val result = client.job(id)) {
            is RelayResult.Ok -> withJob(capture, result.value.job, capture.outcome)
            else -> capture // polling is read-only; the next poll asks again
        }
    }

    /** The planter acted on a refusal (new fix, new diameter, a species from the allowed list): queue it again. */
    suspend fun requeue(capture: CaptureEntity): CaptureEntity = save(
        capture.copy(
            state = CaptureState.QUEUED, attempts = 0, nextAttemptAt = null, lastErrorCode = null,
            lastErrorStatus = null, lastErrorMessage = null, allowedSpecies = null, distanceM = null,
            relayValue = null, updatedAt = clock(),
        ),
    )

    private var lastSessionRefusal: Refusal? = null

    private suspend fun currentSession(): org.biorig.core.queue.Session? {
        val now = clock()
        sessions.load()?.let { if (it.expiresAt > now + 60) return it }
        return when (val r = client.createSession()) {
            is RelayResult.Ok -> Session(r.value.sessionToken, r.value.expiresAt).also { sessions.save(it) }
            is RelayResult.Refused -> { lastSessionRefusal = r.refusal; null }
            is RelayResult.Unreachable -> { lastSessionRefusal = null; null }
        }
    }

    private suspend fun accepted(capture: CaptureEntity, response: RegistrationResponse): CaptureEntity =
        withJob(capture.copy(distanceM = response.distanceM), response.job, response.outcome)

    private suspend fun withJob(capture: CaptureEntity, job: Job, outcome: String?): CaptureEntity {
        val state = when (job.state) {
            Job.STATE_MINTED -> CaptureState.MINTED
            Job.STATE_REJECTED -> CaptureState.REJECTED
            else -> CaptureState.SENT
        }
        return save(
            capture.copy(
                state = state, jobId = job.jobId, jobState = job.state, outcome = outcome, attempts = 0,
                nextAttemptAt = null, lastErrorCode = job.lastErrorCode, lastErrorStatus = null,
                lastErrorMessage = null, cell = job.cell, treeOrdinal = job.treeOrdinal, nullifier = job.nullifier,
                tokenId = job.mint?.tokenId, tba = job.mint?.tba, txHash = job.mint?.txHash,
                mintBlock = job.mint?.block, mintBiomassKg = job.tree.mintBiomassKg, updatedAt = clock(),
            ),
        )
    }

    private suspend fun refused(capture: CaptureEntity, r: Refusal): CaptureEntity {
        val now = clock()
        val next = PlanterMessages.forRefusal(r).next
        if (next is NextStep.Wait) {
            return save(
                capture.copy(
                    nextAttemptAt = now + next.seconds, lastErrorCode = r.code, lastErrorStatus = r.status,
                    lastErrorMessage = r.message, updatedAt = now,
                ),
            )
        }
        if (next is NextStep.RetryLater) return transientFailure(capture, r)
        return save(
            capture.copy(
                state = CaptureState.NEEDS_ATTENTION, nextAttemptAt = null, lastErrorCode = r.code,
                lastErrorStatus = r.status, lastErrorMessage = r.message,
                allowedSpecies = r.allowed?.joinToString(","), distanceM = r.distanceM, relayValue = r.relayValue,
                updatedAt = now,
            ),
        )
    }

    private suspend fun transientFailure(capture: CaptureEntity, r: Refusal?, sessionRefusal: Refusal? = null): CaptureEntity {
        val now = clock()
        // A refused session bootstrap (sessions_per_device_hour, or the relay-wide ceiling) is a wait, not a failure.
        if (sessionRefusal != null && sessionRefusal.code == "rate_limited") {
            return save(
                capture.copy(
                    nextAttemptAt = now + (sessionRefusal.retryAfterS ?: 60), lastErrorCode = sessionRefusal.code,
                    lastErrorStatus = sessionRefusal.status, lastErrorMessage = sessionRefusal.message, updatedAt = now,
                ),
            )
        }
        val failure = r ?: sessionRefusal
        val attempts = capture.attempts + 1
        val exhausted = attempts >= maxAttempts
        return save(
            capture.copy(
                attempts = attempts,
                state = if (exhausted) CaptureState.NEEDS_ATTENTION else CaptureState.QUEUED,
                nextAttemptAt = if (exhausted) null else now + backoffS[minOf(attempts - 1, backoffS.size - 1)],
                lastErrorCode = failure?.code ?: UNREACHABLE, lastErrorStatus = failure?.status,
                lastErrorMessage = failure?.message ?: "no answer from the relay", updatedAt = now,
            ),
        )
    }

    private suspend fun save(c: CaptureEntity): CaptureEntity = c.also { captures.upsert(it) }

    companion object {
        val SESSION_CODES = setOf("session_required", "session_invalid", "session_expired")
        /** Local code for "no HTTP answer"; never sent, never from the relay. */
        const val UNREACHABLE = "unreachable"
    }
}
