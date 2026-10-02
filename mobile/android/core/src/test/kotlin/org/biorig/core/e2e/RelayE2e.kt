package org.biorig.core.e2e

import kotlinx.coroutines.runBlocking
import org.biorig.core.RelayDefaults
import org.biorig.core.geo.H3Index
import org.biorig.core.queue.CaptureEntity
import org.biorig.core.queue.CaptureState
import org.biorig.core.queue.MemoryCaptures
import org.biorig.core.queue.MemorySessions
import org.biorig.core.queue.SubmissionQueue
import org.biorig.core.relay.PlanterMessages
import org.biorig.core.relay.RegistrationBuilder
import org.biorig.core.relay.RelayClient
import org.biorig.core.relay.RelayResult
import org.biorig.core.relay.Refusal
import kotlin.system.exitProcess

/**
 * Driven by tools/relay_e2e.py, which serves the real relay.service.Relay over HTTP (with the relay suite's
 * FakeBroadcaster standing in for the chain). Each step prints what came back and fails the run if it is not what
 * the contract says. Usage: `./gradlew -q :core:relayE2e -Prelay=http://127.0.0.1:PORT`.
 */
fun main(args: Array<String>): Unit = runBlocking {
    val base = args.firstOrNull() ?: error("relay base URL required")
    val client = RelayClient(base)
    val captures = MemoryCaptures()
    val sessions = MemorySessions()
    val queue = SubmissionQueue(client, captures, sessions, { System.currentTimeMillis() / 1000 })
    val now = System.currentTimeMillis() / 1000
    val planterA = "0xD314e37FD8538fe66231EE670B74C9428d03feEa"
    val planterB = "0x" + "b2".repeat(20)
    val lat = 6.428093
    val lng = 3.421974
    var failures = 0

    fun capture(planter: String, north: Double, accuracy: Double = 4.2, species: String = "unspecified") = CaptureEntity(
        RegistrationBuilder.newSubmissionId(), planter, lat + north / 111_320.0, lng, accuracy, now - 20, species, 10,
        null, null, now,
    )

    fun expect(step: String, ok: Boolean, detail: String) {
        println("${if (ok) "ok  " else "FAIL"} $step: $detail")
        if (!ok) failures++
    }

    fun describe(c: CaptureEntity) = "state=${c.state} outcome=${c.outcome} job=${c.jobId} cell=${c.cell} " +
        "ordinal=${c.treeOrdinal} code=${c.lastErrorCode} distance_m=${c.distanceM} allowed=${c.allowedSpecies}" +
        (c.lastErrorCode?.let { code ->
            " planter_sees=\"" + PlanterMessages.forRefusal(
                Refusal(c.lastErrorStatus ?: 0, code, c.lastErrorMessage ?: "", null,
                    kotlinx.serialization.json.JsonObject(
                        listOfNotNull(
                            c.distanceM?.let { "distance_m" to kotlinx.serialization.json.JsonPrimitive(it) },
                            c.allowedSpecies?.let { s -> "allowed" to kotlinx.serialization.json.JsonArray(s.split(",").map { kotlinx.serialization.json.JsonPrimitive(it) }) },
                        ).toMap(),
                    ),
                ),
            ).title + "\""
        } ?: "")

    // 1. a new tree
    val a = queue.send(capture(planterA, 0.0).also { captures.upsert(it) })
    expect("new tree", a.state == CaptureState.SENT && a.outcome == "created", describe(a))
    val cell = H3Index().cellFor(a.lat, a.lng)
    expect("relay derived the cell the phone computed", a.cell == cell, "phone=$cell relay=${a.cell}")
    val n = org.biorig.core.chain.Nullifier(H3Index())
    expect("relay's nullifier is keccak(cell, salt)", a.nullifier == n.forOrdinal(a.cell!!, a.treeOrdinal!!).nullifierHex,
        "relay=${a.nullifier}")

    // 2. the same capture again (a retry that reached the relay twice): the original job, not a second tree
    val again = queue.send(a.copy(state = CaptureState.QUEUED))
    expect("resend is replayed", again.outcome == "replayed" && again.jobId == a.jobId, describe(again))

    // 3. another planter 6 m away
    val b = queue.send(capture(planterB, 6.0).also { captures.upsert(it) })
    expect("collision", b.state == CaptureState.NEEDS_ATTENTION && b.lastErrorCode == "collision", describe(b))

    // 4. a species the relay does not allow: error.allowed is offered, the chosen one goes through
    val c = queue.send(capture(planterA, 80.0, species = "Mangifera indica").also { captures.upsert(it) })
    expect("species_not_allowed with error.allowed", c.lastErrorCode == "species_not_allowed" &&
        c.allowedSpeciesList == RelayDefaults.SPECIES_OPTIONS, describe(c))
    val c2 = queue.send(queue.requeue(c.copy(species = c.allowedSpeciesList.first())))
    expect("resent with an allowed species", c2.state == CaptureState.SENT && c2.outcome == "created", describe(c2))

    // 5. a fix worse than 30 m (the phone's gate would never let this through; the relay refuses it too)
    val d = queue.send(capture(planterA, 200.0, accuracy = 31.0).also { captures.upsert(it) })
    expect("accuracy_too_coarse", d.lastErrorCode == "accuracy_too_coarse", describe(d))

    // 6. occupancy for the pre-check, and the job read-back
    val plot = client.plot(cell)
    expect("plot read", plot is RelayResult.Ok && plot.value.active == 1 && plot.value.resolution == 12, plot.toString())
    val job = client.job(a.jobId!!)
    expect("job read", job is RelayResult.Ok && job.value.job.submissionId == a.submissionId, job.toString().take(160))

    // 7. keep registering until the relay's per-IP hourly limit answers 429 with Retry-After
    var limited: CaptureEntity? = null
    for (i in 1..6) {
        val e = queue.send(capture(planterA, 300.0 + 60 * i).also { captures.upsert(it) })
        println("     extra tree $i: ${describe(e)}")
        if (e.lastErrorCode == "rate_limited") { limited = e; break }
    }
    expect("rate_limited waits Retry-After", limited != null && limited.state == CaptureState.QUEUED &&
        (limited.nextAttemptAt ?: 0) > now, limited?.let { "next_attempt_in=${it.nextAttemptAt!! - now}s ${describe(it)}" } ?: "never limited")

    println(if (failures == 0) "E2E PASS" else "E2E FAIL ($failures)")
    exitProcess(if (failures == 0) 0 else 1)
}
