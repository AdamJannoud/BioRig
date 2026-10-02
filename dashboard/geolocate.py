"""The browser's own geolocation API as a Streamlit component: a static directory, no build step, no new package.

geolocate(...) renders the "use my location" button and returns the last reading the browser handed back:
{"lat", "lng", "accuracy", "ts"} on success, {"error": "denied" | "unavailable" | "unsupported", "ts"} on failure,
or None before the first tap. ts (ms since the epoch) tells a fresh reading from one already applied.
"""
from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

COMPONENT_DIR = Path(__file__).resolve().parent / "components" / "geolocate"
_component = components.declare_component("biorig_geolocate", path=str(COMPONENT_DIR))


def geolocate(*, label: str, waiting: str, found: str, denied: str, unavailable: str, unsupported: str,
              key: str) -> dict | None:
    return _component(label=label, waiting=waiting, found=found, denied=denied, unavailable=unavailable,
                      unsupported=unsupported, key=key, default=None)
