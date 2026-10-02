"""Area 1: the cell index. Cells are the cheap index; metres are the judgement.

- Cell derivation reuses dashboard.h3_nullifier (resolution 12, ~307 m2, ~19 m across).
- R2: salt = "biorig:v1:" + cell + ":" + ordinal, where ordinal is the next tree ordinal in the cell, allocated
  under the cell's write lock together with the row insert. The salt is a pure function of (cell, ordinal), and the
  biorig:v1: prefix can never reproduce the bare "plot-1" salt already on mainnet.
- R3: occupancy is a neighbourhood question judged in metres: every active registration in the cell's k-ring, by
  haversine distance from the fix. Inside COLLISION_RADIUS_M it is the same tree: the same planter gets the existing
  registration back, a different planter is refused with the distance and the existing token id.
- R4 (the accuracy gate) is applied in validate.py, before a cell is ever derived from the fix.
- R5: at most MAX_TREES_PER_CELL active registrations per cell, and a polygon denylist.

With a 20 m radius and resolution-12 cells (at most ~21.7 m corner to corner), two trees in one cell are almost
always within the radius of each other, so through the open path the ceiling is a backstop that seeded or
recovered rows can reach rather than one that distinct fixes normally will.
"""
from __future__ import annotations

import math
import threading
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass

import h3

from dashboard.h3_nullifier import DEFAULT_RESOLUTION, cell_for, nullifier_from_cell

from .config import Limits
from .store import Registration, Store, StoreError
from .validate import Refusal

SALT_PREFIX = "biorig:v1:"
EARTH_RADIUS_M = 6_371_008.8  # IUGG mean radius


def salt_for(cell: str, ordinal: int) -> str:
    """R2. A pure function of (cell, ordinal): reproducible from the record, chosen by nobody."""
    if not h3.is_valid_cell(cell):
        raise ValueError(f"{cell!r} is not a valid H3 cell")
    if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 0:
        raise ValueError(f"tree ordinal must be a non-negative integer, got {ordinal!r}")
    return f"{SALT_PREFIX}{cell}:{ordinal}"


def nullifier_for(cell: str, ordinal: int) -> str:
    """keccak256(uint64(cell) ++ utf8(salt_for(cell, ordinal))) as lowercase 0x-hex, via dashboard.h3_nullifier."""
    return "0x" + nullifier_from_cell(cell, salt_for(cell, ordinal))[1].hex()


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def ring_k(cell: str, radius_m: float) -> int:
    """Smallest k for which grid_disk(cell, k) holds every cell a point within radius_m of any point in `cell` can
    land in. A point in the cell is within e (circumradius) of its centre, the other point's cell centre within
    another e of that point, and on a hex lattice of spacing sqrt(3)e every centre closer than (k+1) * 1.5e is in the
    k-ring. A 10% margin covers H3's cell-to-cell size distortion. For 20 m at resolution 12 this is k=2 (19 cells)."""
    lat, lng = h3.cell_to_latlng(cell)
    e = max(haversine_m(lat, lng, vlat, vlng) for vlat, vlng in h3.cell_to_boundary(cell))
    reach, spacing = 2 * e * 1.1 + radius_m, 1.5 * e / 1.1
    return max(1, math.floor(reach / spacing))


def point_in_polygon(lat: float, lng: float, polygon: tuple[tuple[float, float], ...]) -> bool:
    inside = False
    j = len(polygon) - 1
    for i, (yi, xi) in enumerate(polygon):
        yj, xj = polygon[j]
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


@dataclass(frozen=True)
class Decision:
    kind: str  # new | same_tree | collision
    cell: str
    existing: Registration | None = None
    distance_m: float | None = None


class PlotIndex:
    def __init__(self, store: Store, limits: Limits, denylist: tuple = (), resolution: int = DEFAULT_RESOLUTION):
        self.store = store
        self.limits = limits
        self.denylist = denylist
        self.resolution = resolution
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def cell(self, lat: float, lng: float) -> str:
        return cell_for(lat, lng, self.resolution)

    def neighbourhood(self, cell: str) -> list[str]:
        return list(h3.grid_disk(cell, ring_k(cell, self.limits.collision_radius_m)))

    @contextmanager
    def cell_lock(self, cell: str):
        """The cell's write lock. Held from reading the next ordinal to inserting the row."""
        with self._locks_guard:
            lock = self._locks.setdefault(cell, threading.Lock())
        with lock:
            yield

    def nearest(self, lat: float, lng: float, cell: str) -> tuple[Registration, float] | None:
        """The closest active registration in the cell's neighbourhood, with its distance in metres."""
        best = None
        for reg in self.store.in_cells(self.neighbourhood(cell)):
            d = haversine_m(lat, lng, reg.lat, reg.lng)
            if best is None or d < best[1]:
                best = (reg, d)
        return best

    def decide(self, lat: float, lng: float, planter: str) -> Decision:
        """R3 then R5 for one fix. Raises Refusal for a denylisted area or a full cell."""
        for poly in self.denylist:
            if point_in_polygon(lat, lng, poly):
                raise Refusal(422, "denylisted_area", "the fix is inside an excluded area")
        cell = self.cell(lat, lng)
        near = self.nearest(lat, lng, cell)
        if near is not None and near[1] <= self.limits.collision_radius_m:
            reg, d = near
            kind = "same_tree" if reg.planter_address.lower() == planter.lower() else "collision"
            return Decision(kind, cell, reg, d)
        if self.store.count_active_in_cell(cell) >= self.limits.max_trees_per_cell:
            raise Refusal(422, "cell_full",
                          f"cell {cell} already holds {self.limits.max_trees_per_cell} active registrations",
                          cell=cell, max_trees_per_cell=self.limits.max_trees_per_cell)
        return Decision("new", cell)

    def allocate(self, cell: str, make_values: Callable[[int, str, str], dict],
                 guard: Callable[[int, str, str], Registration | None] | None = None) -> tuple[Registration, bool]:
        """Allocate the next tree ordinal in `cell` and insert the row, under the cell's write lock.

        make_values(ordinal, salt, nullifier) returns the row's other columns. guard(ordinal, salt, nullifier), if
        given, runs inside the lock before the insert; a Registration it returns is used instead of inserting (the
        chain-recovery path), and the result is (that row, False). Otherwise (the new row, True)."""
        with self.cell_lock(cell):
            ordinal = self.store.next_ordinal(cell)
            salt, nullifier = salt_for(cell, ordinal), nullifier_for(cell, ordinal)
            if guard is not None:
                taken = guard(ordinal, salt, nullifier)
                if taken is not None:
                    return taken, False
            with self.store.transaction():
                if self.store.next_ordinal(cell) != ordinal:
                    raise StoreError(f"ordinal {ordinal} in {cell} was taken outside the cell lock")
                values = make_values(ordinal, salt, nullifier)
                row = self.store.insert({**values, "cell": cell, "tree_ordinal": ordinal, "salt": salt,
                                         "nullifier": nullifier})
            return row, True
