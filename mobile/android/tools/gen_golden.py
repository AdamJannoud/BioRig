"""Golden vectors for :core, computed by the repository's own Python rather than typed in.

    .venv/bin/python mobile/android/tools/gen_golden.py           # rewrite core/src/test/resources/golden/vectors.json
    .venv/bin/python mobile/android/tools/gen_golden.py --check   # exit 1 if the committed file is stale

Every number here comes from the modules the relay itself runs: dashboard/allometry.py (the estimate the relay
recomputes and compares), dashboard/h3_nullifier.py (cell and nullifier), relay/plot_index.py (salt, haversine,
k-ring), relay/config.py (limits and the default species allowlist) and relay/validate.py (the field sets). The
Kotlin tests compare :core against this file, so a constant that moves on either side fails a test: on the Python
side `--check` reports the stale file and regenerating changes the expected values; on the Kotlin side the computed
values stop matching.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ANDROID = HERE.parent
REPO = ANDROID.parent.parent
OUT = ANDROID / "core" / "src" / "test" / "resources" / "golden" / "vectors.json"

sys.path.insert(0, str(REPO))

import h3  # noqa: E402
from eth_utils import keccak, to_checksum_address  # noqa: E402

from dashboard import allometry, h3_nullifier  # noqa: E402
from relay import plot_index, validate  # noqa: E402
from relay.config import Limits, RelayConfig  # noqa: E402

# Points spread over the hemispheres, the equator, the antimeridian and the plan's own examples.
POINTS = [
    ("nairobi_dashboard_default", -1.2921, 36.8219),
    ("relay_api_example", -1.2903, 36.8219),
    ("lagos_plan_mockup", 6.428093, 3.421974),
    ("sao_paulo", -23.55052, -46.633308),
    ("jakarta", -6.2088, 106.8456),
    ("near_equator_greenwich", 0.000123, 0.000456),
    ("antimeridian_fiji", -17.7134, 179.9999),
    ("antimeridian_west", -17.7134, -179.9999),
    ("high_north_tromso", 69.6492, 18.9553),
    ("celo_berlin", 52.520008, 13.404954),
    ("quito", -0.180653, -78.467834),
    ("kinshasa", -4.441931, 15.266293),
]

# Pairs for the 20 m rule: around the radius, either side of it, and long baselines.
_LAT, _LNG = 6.428093, 3.421974
_M_PER_DEG_LAT = 111_194.93  # only to place the probes near the boundary; the distances are computed below
HAVERSINE_PAIRS = [
    (_LAT, _LNG, _LAT, _LNG),
    (_LAT, _LNG, _LAT + 19.9 / _M_PER_DEG_LAT, _LNG),
    (_LAT, _LNG, _LAT + 20.0 / _M_PER_DEG_LAT, _LNG),
    (_LAT, _LNG, _LAT + 20.1 / _M_PER_DEG_LAT, _LNG),
    (_LAT, _LNG, _LAT, _LNG + 0.00018),
    (_LAT, _LNG, _LAT + 0.00012, _LNG - 0.00011),
    (-1.2921, 36.8219, -1.2903, 36.8219),
    (52.520008, 13.404954, 48.856613, 2.352222),
    (-17.7134, 179.9999, -17.7134, -179.9999),
    (0.0, 0.0001, 0.0, -0.0001),
]

ADDRESSES = [
    "0xd314e37fd8538fe66231ee670b74c9428d03feea",  # relay-api.md example planter
    "0x04db169ddf8abb80943161c01b2a71dc40384e64",  # mainnet proxy (dashboard/deployment.json)
    "0x21ab8b36177f65ce69e04e281e4aff3db6b5f7e6",  # sepolia proxy
    "0x000000006551c19487814612e58fe06813775758",  # canonical ERC-6551 registry
    "0x5aaeb6053f3e94c9b9a09f33669435e7ef1beaed",  # EIP-55 spec vectors
    "0xfb6916095ca1df60bb79ce92ce3ea74c37c5d359",
    "0xdbf03b407c01e7cd3cbea99509d93f8dddc8c6fb",
    "0xd1220a0cf47c7b9be7a2e6ba89f429762e7b9adb",
]

SIGNATURES = ["isNullifierActive(bytes32)", "getTreeStats(uint256)", "ownerOf(uint256)"]


def build() -> dict:
    limits = Limits()
    allo = []
    for dbh in range(allometry.DBH_MIN_CM, allometry.DBH_MAX_CM + 1):
        e = allometry.estimate(dbh)
        allo.append({"dbh_cm": dbh, "height_m": e.height_m, "biomass_kg": e.biomass_kg, "carbon_kg": e.carbon_kg,
                     "co2e_kg": e.co2e_kg, "mint_biomass_kg": e.mint_biomass_kg})
    densities = [{"dbh_cm": d, "wood_density": rho, "biomass_kg": allometry.biomass_kg(d, rho)}
                 for d in (5, 10, 37, 120) for rho in (0.3, 0.6, 0.85)]

    cells = []
    for name, lat, lng in POINTS:
        d = h3_nullifier.derive(lat, lng, "plot-1")
        k = plot_index.ring_k(d.cell, limits.collision_radius_m)
        cells.append({"name": name, "lat": lat, "lng": lng, "cell": d.cell,
                      "resolution": h3.get_resolution(d.cell), "ring_k": k,
                      "neighbourhood": sorted(h3.grid_disk(d.cell, k))})

    nullifiers = []
    for name, lat, lng in POINTS[:6]:
        cell = h3_nullifier.cell_for(lat, lng)
        for ordinal in (0, 1, 3):
            salt = plot_index.salt_for(cell, ordinal)
            preimage, digest = h3_nullifier.nullifier_from_cell(cell, salt)
            assert "0x" + digest.hex() == plot_index.nullifier_for(cell, ordinal)
            nullifiers.append({"cell": cell, "ordinal": ordinal, "salt": salt, "preimage": "0x" + preimage.hex(),
                               "nullifier": "0x" + digest.hex()})
    pilot = h3_nullifier.derive(-1.2921, 36.8219, "plot-1")  # the seeded mainnet pilot keeps the bare plot-1 salt
    legacy = {"cell": pilot.cell, "salt": pilot.salt, "preimage": "0x" + pilot.preimage.hex(),
              "nullifier": pilot.nullifier_hex}

    haversine = [{"lat1": a, "lng1": b, "lat2": c, "lng2": d, "metres": plot_index.haversine_m(a, b, c, d)}
                 for a, b, c, d in HAVERSINE_PAIRS]

    return {
        "_generated_by": "mobile/android/tools/gen_golden.py from dashboard/allometry.py, dashboard/h3_nullifier.py, "
                         "relay/plot_index.py, relay/config.py and relay/validate.py",
        "constants": {
            "chave_a": allometry.CHAVE_A, "chave_b": allometry.CHAVE_B,
            "height_a": allometry.HEIGHT_A, "height_b": allometry.HEIGHT_B, "height_c": allometry.HEIGHT_C,
            "default_wood_density": allometry.DEFAULT_WOOD_DENSITY, "carbon_fraction": allometry.CARBON_FRACTION,
            "co2_per_c": allometry.CO2_PER_C, "dbh_min_cm": allometry.DBH_MIN_CM, "dbh_max_cm": allometry.DBH_MAX_CM,
            "h3_resolution": h3_nullifier.DEFAULT_RESOLUTION, "salt_prefix": plot_index.SALT_PREFIX,
            "earth_radius_m": plot_index.EARTH_RADIUS_M,
        },
        "limits": {
            "max_accuracy_m": limits.max_accuracy_m, "collision_radius_m": limits.collision_radius_m,
            "fix_max_age_s": limits.fix_max_age_s, "fix_max_future_s": limits.fix_max_future_s,
            "biomass_tolerance_rel": limits.biomass_tolerance_rel,
            "biomass_tolerance_abs_kg": limits.biomass_tolerance_abs_kg,
            "max_trees_per_cell": limits.max_trees_per_cell, "per_session": limits.per_session,
        },
        "default_species": list(RelayConfig.__dataclass_fields__["species"].default),
        "fields": {
            "top": sorted(validate.TOP_FIELDS), "fix": sorted(validate.FIX_FIELDS),
            "tree": sorted(validate.TREE_FIELDS), "client_estimate": sorted(validate.ESTIMATE_FIELDS),
            "forbidden": sorted(validate.FORBIDDEN_FIELDS),
        },
        "allometry": allo,
        "allometry_density": densities,
        "cells": cells,
        "nullifiers": nullifiers,
        "legacy_pilot_nullifier": legacy,
        "haversine": haversine,
        "eip55": [{"lower": a, "checksummed": to_checksum_address(a)} for a in ADDRESSES],
        "selectors": [{"signature": s, "selector": "0x" + keccak(text=s)[:4].hex()} for s in SIGNATURES],
    }


def render(data: dict) -> str:
    return json.dumps(data, indent=1, sort_keys=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if the committed vectors are stale")
    args = ap.parse_args(argv)
    text = render(build())
    if args.check:
        current = OUT.read_text() if OUT.exists() else ""
        if current != text:
            print(f"STALE: {OUT.relative_to(REPO)} no longer matches the repository's Python; rerun without --check",
                  file=sys.stderr)
            return 1
        print(f"ok: {OUT.relative_to(REPO)} matches the repository's Python")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(REPO)}: {len(json.loads(text)['allometry'])} allometry rows, "
          f"{len(json.loads(text)['cells'])} cells, {len(json.loads(text)['nullifiers'])} nullifiers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
