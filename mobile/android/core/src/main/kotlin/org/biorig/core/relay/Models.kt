package org.biorig.core.relay

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

// The wire shapes of docs/relay-api.md (contract v1). Field names are the contract's; nothing here is optional
// unless the contract says so, and nothing here carries a nullifier, salt, cell, ordinal, biomass or token id on
// the way out (the relay refuses those with forbidden_field).

@Serializable
data class RegistrationRequest(
    @SerialName("submission_id") val submissionId: String,
    @SerialName("planter_address") val planterAddress: String,
    val fix: FixBody,
    val tree: TreeBody,
    @SerialName("client_estimate") val clientEstimate: ClientEstimate? = null,
    @SerialName("photo_sha256") val photoSha256: String? = null,
)

@Serializable
data class FixBody(
    val lat: Double,
    val lng: Double,
    @SerialName("accuracy_m") val accuracyM: Double,
    @SerialName("captured_at") val capturedAt: Long,
)

@Serializable
data class TreeBody(
    val species: String,
    @SerialName("dbh_cm") val dbhCm: Int,
)

@Serializable
data class ClientEstimate(
    @SerialName("biomass_kg") val biomassKg: Double? = null,
    @SerialName("co2e_kg") val co2eKg: Double? = null,
)

@Serializable
data class SessionResponse(
    @SerialName("session_token") val sessionToken: String,
    @SerialName("created_at") val createdAt: Long,
    @SerialName("expires_at") val expiresAt: Long,
    @SerialName("registrations_allowed") val registrationsAllowed: Int,
)

@Serializable
data class JobTree(
    val species: String? = null,
    @SerialName("dbh_cm") val dbhCm: Int,
    @SerialName("biomass_kg") val biomassKg: Double? = null,
    @SerialName("co2e_kg") val co2eKg: Double? = null,
    @SerialName("mint_biomass_kg") val mintBiomassKg: Long,
)

@Serializable
data class JobMint(
    @SerialName("token_id") val tokenId: Long,
    val tba: String,
    @SerialName("tx_hash") val txHash: String,
    val block: Long,
)

@Serializable
data class Job(
    @SerialName("job_id") val jobId: String,
    @SerialName("submission_id") val submissionId: String? = null,
    val state: String,
    val cell: String,
    @SerialName("tree_ordinal") val treeOrdinal: Int,
    val salt: String,
    val nullifier: String,
    @SerialName("planter_address") val planterAddress: String,
    val tree: JobTree,
    val attempts: Int = 0,
    @SerialName("next_attempt_at") val nextAttemptAt: Long? = null,
    @SerialName("last_error_code") val lastErrorCode: String? = null,
    val mint: JobMint? = null,
    @SerialName("created_at") val createdAt: Long,
    @SerialName("updated_at") val updatedAt: Long,
    @SerialName("verified_at") val verifiedAt: Long? = null,
    @SerialName("minted_at") val mintedAt: Long? = null,
) {
    val isTerminal: Boolean get() = state == STATE_MINTED || state == STATE_REJECTED

    companion object {
        const val STATE_SUBMITTED = "submitted"
        const val STATE_VERIFIED = "verified"
        const val STATE_MINTED = "minted"
        const val STATE_REJECTED = "rejected"
    }
}

/** 202 created, or 200 replayed / same_tree / recovered. */
@Serializable
data class RegistrationResponse(
    val job: Job,
    val outcome: String,
    @SerialName("distance_m") val distanceM: Double? = null,
)

@Serializable
data class JobResponse(val job: Job)

@Serializable
data class PlotTree(
    @SerialName("tree_ordinal") val treeOrdinal: Int,
    val state: String,
    @SerialName("token_id") val tokenId: Long? = null,
)

@Serializable
data class PlotOccupancy(
    val cell: String,
    val resolution: Int,
    val active: Int,
    @SerialName("max_trees_per_cell") val maxTreesPerCell: Int,
    val full: Boolean,
    @SerialName("neighbourhood_active") val neighbourhoodActive: Int,
    @SerialName("collision_radius_m") val collisionRadiusM: Double,
    val trees: List<PlotTree> = emptyList(),
)
