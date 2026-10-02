"""Area 1: salt allocation, the k-ring distance test, the race, the ceiling, and the seeded pilot."""
from __future__ import annotations

import random
import threading
import time

import h3
import pytest
from eth_utils import keccak

from relay import plot_index as pi
from relay.seed import PILOT_JOB_ID, seed_pilot
from relay.store import StoreError
from relay.validate import Refusal

from .conftest import PILOT_LAT, PILOT_LNG, PLANTER_A, PLANTER_B, offset

CELL = "8c7a6e42ca207ff"  # tools/demo_facts.json demo_h3.cell


def test_salt_is_a_pure_function_of_cell_and_ordinal():
    assert pi.salt_for(CELL, 0) == pi.salt_for(CELL, 0) == "biorig:v1:8c7a6e42ca207ff:0"
    assert pi.salt_for(CELL, 1) != pi.salt_for(CELL, 0)
    other = h3.grid_ring(CELL, 1)[0]
    assert pi.salt_for(other, 0) != pi.salt_for(CELL, 0)
    # the nullifier is keccak256(uint64(cell) ++ utf8(salt)), recomputed independently of dashboard.h3_nullifier
    expected = "0x" + keccak(int(CELL, 16).to_bytes(8, "big") + b"biorig:v1:8c7a6e42ca207ff:0").hex()
    assert pi.nullifier_for(CELL, 0) == expected
    assert pi.nullifier_for(CELL, 0) != pi.nullifier_for(CELL, 1)


def test_new_scheme_can_never_derive_the_bare_mainnet_salt():
    assert all(pi.salt_for(CELL, n).startswith("biorig:v1:") for n in range(50))
    assert "plot-1" not in {pi.salt_for(CELL, n) for n in range(50)}
    with pytest.raises(ValueError):
        pi.salt_for(CELL, -1)
    with pytest.raises(ValueError):
        pi.salt_for("not-a-cell", 0)


def test_neighbourhood_covers_every_cell_within_the_radius():
    """Two fixes within COLLISION_RADIUS_M must always meet in the k-ring search, wherever in the cell they fall."""
    rnd = random.Random(7)
    cell = h3.latlng_to_cell(PILOT_LAT, PILOT_LNG, 12)
    k = pi.ring_k(cell, 20.0)
    assert k == 2  # 19 cells at resolution 12
    disk = set(h3.grid_disk(cell, k))
    boundary = h3.cell_to_boundary(cell)
    for _ in range(3000):
        # a random point inside the cell (rejection sample in its bounding box), and another within 20 m of it
        lats, lngs = [v[0] for v in boundary], [v[1] for v in boundary]
        while True:
            p = (rnd.uniform(min(lats), max(lats)), rnd.uniform(min(lngs), max(lngs)))
            if h3.latlng_to_cell(*p, 12) == cell:
                break
        r, theta = 20.0 * rnd.random() ** 0.5, rnd.uniform(0, 6.283185)
        q = offset(*p, north_m=r * __import__("math").cos(theta), east_m=r * __import__("math").sin(theta))
        assert h3.latlng_to_cell(*q, 12) in disk


def test_jitter_one_tree_twice_in_adjacent_cells_is_a_collision(rig, jitter_pair):
    (alat, alng), (blat, blng) = jitter_pair
    first = rig.submit(alat, alng, planter=PLANTER_A)
    assert first.status == 202, first.body
    second = rig.submit(blat, blng, planter=PLANTER_B, ip="198.51.100.9")
    assert second.status == 409, second.body
    err = second.body["error"]
    assert err["code"] == "collision"
    assert 10.0 < err["distance_m"] < 12.5
    assert err["existing"]["cell"] == first.body["job"]["cell"]
    assert rig.store.counts_by_state()["submitted"] == 1  # not a new tree


def test_jitter_same_planter_gets_the_existing_registration(rig, jitter_pair):
    (alat, alng), (blat, blng) = jitter_pair
    first = rig.submit(alat, alng, planter=PLANTER_A, submission_id="tap-1")
    again = rig.submit(blat, blng, planter=PLANTER_A, submission_id="tap-2", ip="198.51.100.9")
    assert again.status == 200 and again.body["outcome"] == "same_tree"
    assert again.body["job"]["job_id"] == first.body["job"]["job_id"]
    assert sum(rig.store.counts_by_state().values()) == 1


def test_beyond_the_radius_is_a_new_tree(rig):
    a = rig.submit(*offset(PILOT_LAT, PILOT_LNG, north_m=100), planter=PLANTER_A)
    b = rig.submit(*offset(PILOT_LAT, PILOT_LNG, north_m=125), planter=PLANTER_B, ip="198.51.100.9")
    assert a.status == 202 and b.status == 202
    assert a.body["job"]["nullifier"] != b.body["job"]["nullifier"]


def test_two_allocations_racing_for_one_cell_get_distinct_ordinals(rig, monkeypatch):
    """The cell write lock spans reading the next ordinal and inserting the row. The read is slowed so both threads
    are inside the window at once: without the lock both read 0 and the second insert fails."""
    store, index = rig.store, rig.relay.index
    real_next = store.next_ordinal

    def slow_next(cell):
        n = real_next(cell)
        time.sleep(0.05)
        return n

    monkeypatch.setattr(store, "next_ordinal", slow_next)
    barrier = threading.Barrier(2)
    results, errors = [], []

    def values(planter):
        return lambda ordinal, salt, nullifier: {
            "lat": PILOT_LAT, "lng": PILOT_LNG, "location_source": "fix", "dbh_cm": 10, "mint_biomass_kg": 20,
            "planter_address": planter, "state": "submitted"}

    def run(planter):
        barrier.wait()
        try:
            results.append(index.allocate(CELL, values(planter))[0])
        except Exception as exc:  # pragma: no cover - the failure this test exists to catch
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(p,)) for p in (PLANTER_A, PLANTER_B)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    assert sorted(r.tree_ordinal for r in results) == [0, 1]
    assert len({r.nullifier for r in results}) == 2
    assert {r.salt for r in results} == {pi.salt_for(CELL, 0), pi.salt_for(CELL, 1)}


def test_seeded_pilot_is_inside_the_index(rig):
    row, inserted = seed_pilot(rig.store)
    assert inserted and row.id == PILOT_JOB_ID
    assert seed_pilot(rig.store)[1] is False  # idempotent
    # found by a cell query
    in_cell = rig.store.in_cells([CELL])
    assert [(r.token_id, r.salt, r.tree_ordinal, r.nullifier) for r in in_cell] == [
        (1, "plot-1", 0, "0xb7a55a6b1b7e4fe0fba76f303772cba7fdf3715d4030e3fcd91ed297c756d741")]
    plot = rig.call("GET", f"/v1/plots/{CELL}")
    assert plot.status == 200
    assert plot.body["active"] == 1 and plot.body["trees"] == [{"tree_ordinal": 0, "state": "minted", "token_id": 1}]
    # and it takes part in the collision test: a fix 11 m from the mainnet tree collides with token 1
    resp = rig.submit(*offset(PILOT_LAT, PILOT_LNG, east_m=11), planter=PLANTER_B)
    assert resp.status == 409 and resp.body["error"]["existing"]["token_id"] == 1
    # the next ordinal in the pilot's cell is 1, so the new scheme never re-derives ordinal 0 there
    assert rig.store.next_ordinal(CELL) == 1


def test_seed_refuses_a_store_for_another_chain(make_rig):
    rig = make_rig(RELAY_CHAIN_ID="11142220", fake=None)
    with pytest.raises(StoreError):
        seed_pilot(rig.store)


def test_cell_ceiling_refuses_rather_than_queueing_for_review(rig):
    """No human gate before verified (owner decision 2): a full cell is a refusal."""
    for n in range(4):  # four active trees recorded in one cell (as seeded or recovered rows would be)
        lat, lng = h3.cell_to_latlng(CELL)
        rig.store.insert({"nullifier": pi.nullifier_for(CELL, n), "cell": CELL, "tree_ordinal": n,
                          "salt": pi.salt_for(CELL, n), "lat": lat + 1.0, "lng": lng,  # far away: no collision
                          "location_source": "record", "dbh_cm": 10, "mint_biomass_kg": 20,
                          "planter_address": PLANTER_A, "state": "minted"})
    with pytest.raises(Refusal) as exc:
        rig.relay.index.decide(PILOT_LAT, PILOT_LNG, PLANTER_B)
    assert exc.value.code == "cell_full"


def test_denylisted_area_is_refused(make_rig, tmp_path):
    poly = tmp_path / "deny.json"
    poly.write_text('[[[-1.30, 36.81], [-1.28, 36.81], [-1.28, 36.83], [-1.30, 36.83]]]')
    rig = make_rig(DENYLIST_FILE=str(poly))
    resp = rig.submit(PILOT_LAT, PILOT_LNG)
    assert resp.status == 422 and resp.body["error"]["code"] == "denylisted_area"
