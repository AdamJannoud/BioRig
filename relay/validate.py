"""Every client field, checked. A field that fails is a refusal with a code and a reason, never a clamp.

R1: the client sends no nullifier, no reference/salt, no cell and no ordinal. Those are the relay's to derive, so a
body carrying any of them is refused outright (forbidden_field) rather than having the value ignored: a client that
still sends them is one that believes it chooses the plot's identity.

The numbers are recomputed, not received. The relay runs allometry.estimate itself; a client estimate is optional
and only compared, and a disagreement beyond tolerance is a stale or tampered client (estimate_mismatch).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from eth_utils import is_checksum_address, to_checksum_address

from dashboard import allometry

from .config import Limits

FORBIDDEN_FIELDS = frozenset({"nullifier", "spatial_nullifier", "spatialNullifier", "reference", "ref", "salt",
                              "cell", "h3_cell", "tree_ordinal", "plot_index", "ordinal", "biomass_kg", "co2e_kg",
                              "token_id"})
TOP_FIELDS = frozenset({"submission_id", "planter_address", "fix", "tree", "client_estimate", "photo_sha256"})
FIX_FIELDS = frozenset({"lat", "lng", "accuracy_m", "captured_at"})
TREE_FIELDS = frozenset({"species", "dbh_cm"})
ESTIMATE_FIELDS = frozenset({"biomass_kg", "co2e_kg"})
_SUBMISSION_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class Refusal(Exception):
    """A request the relay will not act on. `status` is the HTTP status, `code` the stable machine-readable reason."""

    def __init__(self, status: int, code: str, message: str, **detail):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, **self.detail}}


def invalid(field: str, message: str, code: str = "invalid_field", status: int = 400) -> Refusal:
    return Refusal(status, code, f"{field}: {message}", field=field)


@dataclass(frozen=True)
class Submission:
    submission_id: str
    planter_address: str  # checksummed
    lat: float
    lng: float
    accuracy_m: float
    captured_at: int
    species: str
    dbh_cm: int
    biomass_kg: float  # the relay's figures
    co2e_kg: float
    mint_biomass_kg: int
    client_biomass_kg: float | None
    client_co2e_kg: float | None
    photo_sha256: str | None


def _object(value, field: str, allowed: frozenset) -> dict:
    if not isinstance(value, dict):
        raise invalid(field, "must be an object")
    for key in value:
        if key in allowed:
            continue
        if key in FORBIDDEN_FIELDS:
            raise Refusal(400, "forbidden_field",
                          f"{field}.{key}: the relay derives the plot's identity and its figures; the client sends "
                          "only the measurement and the fix", field=f"{field}.{key}")
        raise invalid(f"{field}.{key}", "unknown field", code="unknown_field")
    return value


def _required(obj: dict, key: str, field: str):
    if key not in obj or obj[key] is None:
        raise invalid(field, "is required", code="missing_field")
    return obj[key]


def _number(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise invalid(field, "must be a finite number")
    return float(value)


def _integer(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid(field, "must be an integer")
    return value


def parse_submission(body, limits: Limits, species_allowlist: tuple[str, ...], now: float) -> Submission:
    """Validate a POST /v1/registrations body. Raises Refusal on the first field that fails."""
    if not isinstance(body, dict):
        raise invalid("body", "must be a JSON object")
    for key in body:
        if key in FORBIDDEN_FIELDS:
            raise Refusal(400, "forbidden_field",
                          f"{key}: the relay derives the plot's identity and its figures; the client sends only the "
                          "measurement and the fix", field=key)
        if key not in TOP_FIELDS:
            raise invalid(key, "unknown field", code="unknown_field")

    submission_id = _required(body, "submission_id", "submission_id")
    if not isinstance(submission_id, str) or not _SUBMISSION_ID_RE.match(submission_id):
        raise invalid("submission_id", "must be 1-64 characters of [A-Za-z0-9_-]")

    planter = _required(body, "planter_address", "planter_address")
    if not isinstance(planter, str) or not _ADDRESS_RE.match(planter):
        raise invalid("planter_address", "must be a 0x-prefixed 20-byte hex address")
    if planter != planter.lower() and planter[2:] != planter[2:].upper() and not is_checksum_address(planter):
        raise invalid("planter_address", "mixed-case address fails its EIP-55 checksum")
    if int(planter, 16) == 0:
        raise invalid("planter_address", "the zero address cannot hold a token")

    fix = _object(_required(body, "fix", "fix"), "fix", FIX_FIELDS)
    lat = _number(_required(fix, "lat", "fix.lat"), "fix.lat")
    lng = _number(_required(fix, "lng", "fix.lng"), "fix.lng")
    if not -90.0 <= lat <= 90.0:
        raise invalid("fix.lat", f"{lat} is outside [-90, 90]", code="out_of_range", status=422)
    if not -180.0 <= lng <= 180.0:
        raise invalid("fix.lng", f"{lng} is outside [-180, 180]", code="out_of_range", status=422)
    if lat == 0.0 and lng == 0.0:
        raise invalid("fix", "0, 0 is a failed fix, not a place", code="out_of_range", status=422)
    accuracy = _number(_required(fix, "accuracy_m", "fix.accuracy_m"), "fix.accuracy_m")
    if accuracy <= 0:
        raise invalid("fix.accuracy_m", "must be positive", code="out_of_range", status=422)
    if accuracy > limits.max_accuracy_m:  # R4: refused, not rounded
        raise Refusal(422, "accuracy_too_coarse",
                      f"fix.accuracy_m: {accuracy:g} m is worse than the {limits.max_accuracy_m:g} m a tree can be "
                      "placed with", field="fix.accuracy_m", max_accuracy_m=limits.max_accuracy_m)
    captured_at = _integer(_required(fix, "captured_at", "fix.captured_at"), "fix.captured_at")
    if captured_at > now + limits.fix_max_future_s:
        raise Refusal(422, "fix_in_future", "fix.captured_at is in the future", field="fix.captured_at")
    if captured_at < now - limits.fix_max_age_s:
        raise Refusal(422, "fix_stale", f"fix.captured_at is older than {limits.fix_max_age_s} s",
                      field="fix.captured_at", max_age_s=limits.fix_max_age_s)

    tree = _object(_required(body, "tree", "tree"), "tree", TREE_FIELDS)
    species = _required(tree, "species", "tree.species")
    if not isinstance(species, str) or species not in species_allowlist:
        raise Refusal(422, "species_not_allowed", "tree.species is not on the allowlist", field="tree.species",
                      allowed=list(species_allowlist))
    dbh = _integer(_required(tree, "dbh_cm", "tree.dbh_cm"), "tree.dbh_cm")
    if not allometry.DBH_MIN_CM <= dbh <= allometry.DBH_MAX_CM:
        raise Refusal(422, "dbh_out_of_bounds",
                      f"tree.dbh_cm: {dbh} cm is outside {allometry.DBH_MIN_CM}-{allometry.DBH_MAX_CM} cm",
                      field="tree.dbh_cm", min_cm=allometry.DBH_MIN_CM, max_cm=allometry.DBH_MAX_CM)
    est = allometry.estimate(dbh)

    client_biomass = client_co2e = None
    if body.get("client_estimate") is not None:
        ce = _object(body["client_estimate"], "client_estimate", ESTIMATE_FIELDS)
        for key, ours in (("biomass_kg", est.biomass_kg), ("co2e_kg", est.co2e_kg)):
            if ce.get(key) is None:
                continue
            theirs = _number(ce[key], f"client_estimate.{key}")
            tolerance = max(limits.biomass_tolerance_abs_kg, limits.biomass_tolerance_rel * ours)
            if abs(theirs - ours) > tolerance:
                raise Refusal(422, "estimate_mismatch",
                              f"client_estimate.{key}: {theirs:g} disagrees with the relay's {ours:.2f} for "
                              f"{dbh} cm beyond {tolerance:.2f}", field=f"client_estimate.{key}",
                              relay_value=round(ours, 3))
            if key == "biomass_kg":
                client_biomass = theirs
            else:
                client_co2e = theirs

    photo = body.get("photo_sha256")
    if photo is not None and (not isinstance(photo, str) or not _SHA256_RE.match(photo)):
        raise invalid("photo_sha256", "must be 64 lowercase hex characters")

    return Submission(submission_id, to_checksum_address(planter), lat, lng, accuracy, captured_at, species, dbh,
                      est.biomass_kg, est.co2e_kg, est.mint_biomass_kg, client_biomass, client_co2e, photo)
