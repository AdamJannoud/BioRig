"""R1 and R4 and the numbers: every client field is a refusal, never a clamp."""
from __future__ import annotations

import pytest

from relay.config import Limits
from relay.validate import FORBIDDEN_FIELDS, Refusal, parse_submission

from .conftest import PILOT_LAT, PILOT_LNG, PLANTER_A

NOW = 1_800_000_000


def body(**over):
    b = {"submission_id": "s-1", "planter_address": PLANTER_A,
         "fix": {"lat": PILOT_LAT, "lng": PILOT_LNG, "accuracy_m": 8.0, "captured_at": NOW - 30},
         "tree": {"species": "unspecified", "dbh_cm": 10}}
    b.update(over)
    return b


def refused(b) -> Refusal:
    with pytest.raises(Refusal) as exc:
        parse_submission(b, Limits(), ("unspecified",), NOW)
    return exc.value


def test_a_clean_body_is_accepted_and_the_figures_are_the_relays():
    sub = parse_submission(body(), Limits(), ("unspecified",), NOW)
    assert sub.dbh_cm == 10 and sub.mint_biomass_kg == 20  # allometry: 19.9 kg for 10 cm, the pilot's 20
    assert sub.planter_address.lower() == PLANTER_A and sub.planter_address != PLANTER_A  # checksummed


@pytest.mark.parametrize("key", ["nullifier", "reference", "salt", "cell", "tree_ordinal", "plot_index"])
def test_client_supplied_identity_is_refused(key):
    err = refused(body(**{key: "plot-1"}))
    assert err.code == "forbidden_field" and err.status == 400


def test_client_supplied_identity_inside_a_nested_object_is_refused():
    b = body()
    b["tree"]["nullifier"] = "0x" + "00" * 32
    assert refused(b).code == "forbidden_field"
    b = body()
    b["fix"]["reference"] = "plot-2"
    assert refused(b).code == "forbidden_field"


def test_client_figures_are_not_accepted_as_figures():
    assert "biomass_kg" in FORBIDDEN_FIELDS
    assert refused(body(biomass_kg=999)).code == "forbidden_field"


def test_accuracy_worse_than_the_gate_is_refused_not_rounded():
    b = body()
    b["fix"]["accuracy_m"] = 30.5
    err = refused(b)
    assert err.code == "accuracy_too_coarse" and err.status == 422
    b["fix"]["accuracy_m"] = 30.0
    assert parse_submission(b, Limits(), ("unspecified",), NOW).accuracy_m == 30.0


@pytest.mark.parametrize("field,value,code", [
    ("lat", 91.0, "out_of_range"), ("lng", -181.0, "out_of_range"), ("lat", "1.0", "invalid_field"),
    ("lat", True, "invalid_field"), ("accuracy_m", 0, "out_of_range"), ("captured_at", NOW - 3600, "fix_stale"),
    ("captured_at", NOW + 3600, "fix_in_future"), ("captured_at", 1.5, "invalid_field")])
def test_fix_fields(field, value, code):
    b = body()
    b["fix"][field] = value
    assert refused(b).code == code


def test_tree_fields():
    for dbh in (1, 121):
        b = body()
        b["tree"]["dbh_cm"] = dbh
        assert refused(b).code == "dbh_out_of_bounds"
    b = body()
    b["tree"]["dbh_cm"] = 10.5
    assert refused(b).code == "invalid_field"
    b = body()
    b["tree"]["species"] = "oak"
    assert refused(b).code == "species_not_allowed"


def test_planter_address():
    assert refused(body(planter_address="0x123")).code == "invalid_field"
    assert refused(body(planter_address="0x" + "0" * 40)).code == "invalid_field"
    assert refused(body(planter_address="0xA1a1a1a1A1A1a1A1A1a1a1a1a1a1A1A1A1a1A1aa")).code == "invalid_field"


def test_client_estimate_is_compared_not_trusted():
    ok = parse_submission(body(client_estimate={"biomass_kg": 19.9}), Limits(), ("unspecified",), NOW)
    assert ok.client_biomass_kg == 19.9 and round(ok.biomass_kg, 1) == 19.9
    assert refused(body(client_estimate={"biomass_kg": 40})).code == "estimate_mismatch"


def test_unknown_and_missing_fields():
    assert refused(body(colour="green")).code == "unknown_field"
    b = body()
    del b["fix"]
    assert refused(b).code == "missing_field"
    assert refused(body(submission_id="has spaces")).code == "invalid_field"
    assert refused(body(photo_sha256="XYZ")).code == "invalid_field"


def test_forbidden_field_over_http_creates_no_row(rig):
    token = rig.session()
    b = rig.body(PILOT_LAT, PILOT_LNG, nullifier="0x" + "ab" * 32)
    resp = rig.call("POST", "/v1/registrations", b, token=token)
    assert resp.status == 400 and resp.body["error"]["code"] == "forbidden_field"
    assert sum(rig.store.counts_by_state().values()) == 0
