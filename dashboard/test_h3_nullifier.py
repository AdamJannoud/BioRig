import h3
import pytest
from eth_utils import keccak

from dashboard import h3_nullifier as hn

LAT, LNG = -1.2921, 36.8219  # Nairobi, the dashboard default


def test_cell_is_resolution_12_and_valid():
    cell = hn.cell_for(LAT, LNG)
    assert h3.is_valid_cell(cell)
    assert h3.get_resolution(cell) == 12


def test_deterministic_and_known_vector():
    a = hn.derive(LAT, LNG, "plot-1")
    b = hn.derive(LAT, LNG, "plot-1")
    assert a.nullifier == b.nullifier
    assert a.cell == "8c7a6e42ca207ff"
    # independent recomputation of keccak256(abi.encodePacked(uint64(cell), bytes(salt)))
    expected = keccak(int(a.cell, 16).to_bytes(8, "big") + b"plot-1")
    assert a.nullifier == expected
    assert a.preimage == int(a.cell, 16).to_bytes(8, "big") + b"plot-1"


def test_genuine_bytes32():
    d = hn.derive(LAT, LNG, "x")
    assert isinstance(d.nullifier, bytes) and len(d.nullifier) == 32 and any(d.nullifier)
    assert d.nullifier_hex.startswith("0x") and len(d.nullifier_hex) == 66


def test_different_salt_same_cell_differs():
    a, b = hn.derive(LAT, LNG, "salt-a"), hn.derive(LAT, LNG, "salt-b")
    assert a.cell == b.cell and a.nullifier != b.nullifier


def test_different_cell_same_salt_differs():
    a = hn.derive(LAT, LNG, "s")
    b = hn.derive(LAT + 0.01, LNG, "s")
    assert a.cell != b.cell and a.nullifier != b.nullifier


def test_nearby_points_in_same_cell_collide():
    d = hn.derive(LAT, LNG, "s")
    lat, lng = h3.cell_to_latlng(d.cell)
    assert hn.derive(lat, lng, "s").nullifier == d.nullifier


def test_resolution_changes_cell():
    assert hn.derive(LAT, LNG, "s", 9).cell != hn.derive(LAT, LNG, "s", 12).cell


@pytest.mark.parametrize("lat,lng,res", [(91, 0, 12), (0, 181, 12), (0, 0, 16), (0, 0, -1)])
def test_rejects_out_of_range(lat, lng, res):
    with pytest.raises(ValueError):
        hn.cell_for(lat, lng, res)


def test_rejects_empty_salt_and_bad_cell():
    with pytest.raises(ValueError, match="salt"):
        hn.derive(LAT, LNG, "")
    with pytest.raises(ValueError, match="valid H3"):
        hn.nullifier_from_cell("zz", "s")


@pytest.mark.parametrize("bad,exc", [(b"\x00" * 32, ValueError), (b"\x01" * 31, ValueError), ("0x" + "1" * 64, TypeError)])
def test_assert_bytes32_rejects(bad, exc):
    with pytest.raises(exc):
        hn.assert_bytes32(bad)


def test_cell_area_label():
    assert 250 < hn.derive(LAT, LNG, "s").cell_area_m2 < 350
