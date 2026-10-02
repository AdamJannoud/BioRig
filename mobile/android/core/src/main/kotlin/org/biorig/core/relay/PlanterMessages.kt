package org.biorig.core.relay

import org.biorig.core.RelayDefaults
import kotlin.math.ceil
import kotlin.math.roundToInt

/** What the planter can do about a refusal. The UI offers exactly one next step for each. */
sealed interface NextStep {
    /** Take a new fix at the tree (accuracy, staleness, a clock ahead of the relay's). */
    data object Refix : NextStep
    /** The spot is taken, full or excluded: this tree cannot be registered here. */
    data object PickAnotherTree : NextStep
    /** Re-enter the diameter. */
    data object Remeasure : NextStep
    /** Choose one of the species the relay named in `error.allowed`. */
    data class ChooseSpecies(val allowed: List<String>) : NextStep
    /** Re-enter the planter address. */
    data object FixAddress : NextStep
    /** The queue retries by itself after [seconds]. */
    data class Wait(val seconds: Long) : NextStep
    /** The relay could not answer for reasons on its side; retried with the same submission id. */
    data object RetryLater : NextStep
    /** The request itself is malformed for this relay: an out-of-date app, not something the planter can fix. */
    data object UpdateApp : NextStep
}

data class PlanterMessage(val title: String, val body: String, val next: NextStep)

/**
 * Every refusal the relay documents, worded for the field: no codes, no stack traces. Built from docs/relay-api.md's
 * error table; PlanterMessagesTest walks that table's 422/409/429 codes so a new code cannot go unworded.
 */
object PlanterMessages {
    fun forRefusal(r: Refusal): PlanterMessage = when (r.code) {
        "accuracy_too_coarse" -> PlanterMessage(
            "Position not precise enough",
            "The relay places a tree to within ${RelayDefaults.MAX_ACCURACY_M.roundToInt()} m. Walk into the open, " +
                "away from walls and canopy, and take a new fix.",
            NextStep.Refix,
        )
        "fix_stale" -> PlanterMessage(
            "This fix is too old",
            "The relay accepts a position for ${RelayDefaults.FIX_MAX_AGE_S / 60} minutes after it is taken. " +
                "Go back to the tree and take a new fix; the photo and diameter are kept.",
            NextStep.Refix,
        )
        "fix_in_future" -> PlanterMessage(
            "The phone's clock is ahead",
            "The fix is dated later than the relay's clock. Turn on automatic date and time, then take a new fix.",
            NextStep.Refix,
        )
        "out_of_range" -> PlanterMessage(
            "That position is not a place",
            "The phone reported an impossible position. Take a new fix.",
            NextStep.Refix,
        )
        "collision" -> PlanterMessage(
            "This plot is taken",
            "Another planter registered a tree ${r.distanceM?.let { "${it.roundToInt()} m" } ?: "nearby"} away" +
                (r.existingTokenId?.let { " (token #$it)" } ?: "") + ". Pick a different tree.",
            NextStep.PickAnotherTree,
        )
        "cell_full" -> PlanterMessage(
            "This plot is full",
            "This spot already holds the most trees the relay registers in one place. Pick a tree further away.",
            NextStep.PickAnotherTree,
        )
        "denylisted_area" -> PlanterMessage(
            "Registrations are closed here",
            "This position is inside an area the relay excludes. Pick a tree outside it.",
            NextStep.PickAnotherTree,
        )
        "estimate_mismatch" -> PlanterMessage(
            "Estimate outside tolerance",
            "Relay computed ${r.relayValue?.let { "%.1f kg".format(it) } ?: "a different figure"} for this diameter. " +
                "Re-enter the measurement; if this repeats, update the app.",
            NextStep.Remeasure,
        )
        "dbh_out_of_bounds" -> PlanterMessage(
            "Diameter out of range",
            "Enter a trunk diameter between 2 and 120 cm.",
            NextStep.Remeasure,
        )
        "species_not_allowed" -> {
            val allowed = r.allowed.orEmpty()
            PlanterMessage(
                "Species not allowed",
                if (allowed.isEmpty()) "This relay accepts no species at the moment. Ask your operator."
                else "This relay accepts: ${allowed.joinToString(", ")}. Choose one and send again.",
                NextStep.ChooseSpecies(allowed),
            )
        }
        "rate_limited" -> {
            val s = r.retryAfterS ?: 60
            PlanterMessage("The relay asked us to wait", "Sending again in ${humanDuration(s)}. Nothing is lost.", NextStep.Wait(s))
        }
        "submission_conflict" -> PlanterMessage(
            "Already sent with other details",
            "This capture reached the relay before with a different address or diameter. Capture the tree again.",
            NextStep.PickAnotherTree,
        )
        "chain_unavailable", "recovery_pending", "index_inconsistent", "internal" -> PlanterMessage(
            "The relay cannot decide yet",
            "It could not check the chain for this plot. The capture stays queued and is sent again.",
            NextStep.RetryLater,
        )
        else -> if (r.field == "planter_address") {
            PlanterMessage("Check the planter address", "The relay could not use this address. Re-enter it.", NextStep.FixAddress)
        } else if (r.status >= 500) {
            PlanterMessage("The relay cannot decide yet", "The capture stays queued and is sent again.", NextStep.RetryLater)
        } else {
            PlanterMessage(
                "This app needs an update",
                "The relay did not accept the request this version builds. Update the app; the capture is kept.",
                NextStep.UpdateApp,
            )
        }
    }

    fun humanDuration(seconds: Long): String = when {
        seconds < 90 -> "$seconds s"
        seconds < 5400 -> "${ceil(seconds / 60.0).toInt()} min"
        else -> "${ceil(seconds / 3600.0).toInt()} h"
    }
}
