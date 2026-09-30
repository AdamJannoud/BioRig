"""lat/lng -> H3 cell -> bytes32 spatialNullifier.

nullifier = keccak256(uint64(h3Cell) ++ utf8(salt))
          = Solidity keccak256(abi.encodePacked(uint64(cell), bytes(salt)))

The cell is packed as its 8-byte big-endian index so the value can be reproduced on chain or with
`cast keccak $(cast concat-hex <cell as uint64> <salt hex>)`. The coordinates themselves never go on chain.
"""
from __future__ import annotations

from dataclasses import dataclass

import h3
from eth_utils import keccak

DEFAULT_RESOLUTION = 12  # ~307 m2 average cell area


@dataclass(frozen=True)
class NullifierDerivation:
    lat: float
    lng: float
    resolution: int
    cell: str  # H3 index as hex string, e.g. '8c7a6e4c9b0d1ff'
    salt: str
    preimage: bytes
    nullifier: bytes  # exactly 32 bytes, never zero

    @property
    def nullifier_hex(self) -> str:
        return "0x" + self.nullifier.hex()

    @property
    def cell_area_m2(self) -> float:
        return h3.average_hexagon_area(self.resolution, unit="m^2")


def cell_for(lat: float, lng: float, resolution: int = DEFAULT_RESOLUTION) -> str:
    if not -90.0 <= lat <= 90.0:
        raise ValueError(f"latitude {lat} out of range [-90, 90]")
    if not -180.0 <= lng <= 180.0:
        raise ValueError(f"longitude {lng} out of range [-180, 180]")
    if not 0 <= resolution <= 15:
        raise ValueError(f"H3 resolution {resolution} out of range [0, 15]")
    return h3.latlng_to_cell(lat, lng, resolution)


def nullifier_from_cell(cell: str, salt: str) -> tuple[bytes, bytes]:
    """Return (preimage, nullifier). Raises ValueError on an invalid cell or empty salt."""
    if not h3.is_valid_cell(cell):
        raise ValueError(f"{cell!r} is not a valid H3 cell")
    if salt == "":
        raise ValueError("salt must be non-empty")
    preimage = h3.str_to_int(cell).to_bytes(8, "big") + salt.encode("utf-8")
    digest = keccak(preimage)
    assert_bytes32(digest)
    return preimage, digest


def assert_bytes32(value: bytes) -> None:
    """The contract rejects bytes32(0) with InvalidNullifier; anything not 32 bytes cannot be a bytes32."""
    if not isinstance(value, (bytes, bytearray)):
        raise TypeError(f"nullifier must be bytes, got {type(value).__name__}")
    if len(value) != 32:
        raise ValueError(f"nullifier must be exactly 32 bytes, got {len(value)}")
    if not any(value):
        raise ValueError("nullifier is bytes32(0), which mintTree rejects with InvalidNullifier")


def derive(lat: float, lng: float, salt: str, resolution: int = DEFAULT_RESOLUTION) -> NullifierDerivation:
    cell = cell_for(lat, lng, resolution)
    preimage, digest = nullifier_from_cell(cell, salt)
    return NullifierDerivation(lat, lng, resolution, cell, salt, preimage, digest)
