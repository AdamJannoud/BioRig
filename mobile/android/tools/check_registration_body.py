"""Run the exact POST /v1/registrations body :core builds through the relay's own validator.

    .venv/bin/python mobile/android/tools/check_registration_body.py

Asks Gradle for the body (`:core:emitRegistrationBody`, a capture taken now), then calls
relay.validate.parse_submission on it with the relay's default limits (relay.config.load_limits on an empty
environment) and its default species allowlist, at the current time. Exit 0 when the relay accepts it.

Two controls run on the same body afterwards, so an accepting validator is shown to be the discriminating one:
adding a `cell` must be refused forbidden_field, and doubling the client estimate must be refused estimate_mismatch.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import time
from pathlib import Path

ANDROID = Path(__file__).resolve().parent.parent
REPO = ANDROID.parent.parent
sys.path.insert(0, str(REPO))

from relay.config import RelayConfig, load_limits  # noqa: E402
from relay.validate import Refusal, parse_submission  # noqa: E402


def emit_body() -> str:
    out = subprocess.run(["./gradlew", "-q", "--console=plain", ":core:emitRegistrationBody"], cwd=ANDROID,
                         check=True, capture_output=True, text=True).stdout
    lines = [ln for ln in out.splitlines() if ln.startswith("{")]
    if len(lines) != 1:
        sys.exit(f"expected one JSON line from :core:emitRegistrationBody, got:\n{out}")
    return lines[0]


def main() -> int:
    raw = emit_body()
    print("body built by :core (verbatim):")
    print(raw)
    body = json.loads(raw)
    limits = load_limits({})
    species = RelayConfig.__dataclass_fields__["species"].default
    now = time.time()
    try:
        sub = parse_submission(body, limits, species, now)
    except Refusal as r:
        print(f"REFUSED by relay/validate.py: {r.status} {json.dumps(r.body())}")
        return 1
    print(f"\naccepted by relay/validate.py.parse_submission (limits: max_accuracy_m={limits.max_accuracy_m}, "
          f"fix_max_age_s={limits.fix_max_age_s}, biomass_tolerance_rel={limits.biomass_tolerance_rel}; "
          f"species allowlist={list(species)})")
    print(f"  relay figures: biomass_kg={sub.biomass_kg:.6f} co2e_kg={sub.co2e_kg:.6f} "
          f"mint_biomass_kg={sub.mint_biomass_kg}")
    print(f"  client sent:   biomass_kg={sub.client_biomass_kg:.6f} co2e_kg={sub.client_co2e_kg:.6f}")
    print(f"  planter (checksummed by the relay): {sub.planter_address}")

    failures = 0
    for label, mutate, expected in (
        ("add fix.cell", lambda b: b["fix"].__setitem__("cell", "8c7a6e42ca207ff"), "forbidden_field"),
        ("add top-level nullifier", lambda b: b.__setitem__("nullifier", "0x" + "ab" * 32), "forbidden_field"),
        ("double client_estimate.biomass_kg",
         lambda b: b["client_estimate"].__setitem__("biomass_kg", b["client_estimate"]["biomass_kg"] * 2),
         "estimate_mismatch"),
        ("species not on the allowlist", lambda b: b["tree"].__setitem__("species", "Mangifera indica"),
         "species_not_allowed"),
    ):
        b = copy.deepcopy(body)
        mutate(b)
        try:
            parse_submission(b, limits, species, now)
            got = "accepted"
        except Refusal as r:
            got = r.code
        ok = got == expected
        failures += not ok
        print(f"control: {label:38s} -> {got} ({'as expected' if ok else 'UNEXPECTED, wanted ' + expected})")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
