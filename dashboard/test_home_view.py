"""Home, offline: the bare URL opens it, its figures come from the chain, both calls to action lead into the demo,
and the published ?view= names still open the screens they always did.

The chain is the offline model test_planter_view.py uses (one tree, token 1, on the pilot plot)."""
import functools
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from dashboard import chain as chain_mod
from dashboard import config
from dashboard.test_app_signing import HEX64
from dashboard.test_config import _key_env
from dashboard.test_planter_view import JARGON, PlanterChain, _ok, _visible

APP = Path(__file__).resolve().parent / "app.py"
HERO = "Every tree measured,"
PLANTER = "How thick is the trunk?"
PROTOCOL = "Live state · getTreeStats(1)"


def _render(tmp_path, monkeypatch, view=None):
    _key_env(tmp_path, monkeypatch)
    monkeypatch.setenv("PRIVATE_KEY", HEX64)
    monkeypatch.setattr(chain_mod, "Chain", PlanterChain)
    monkeypatch.setattr(config, "load_settings", functools.partial(config.load_settings, tmp_path, secrets={}))
    st.cache_resource.clear()
    st.cache_data.clear()
    at = AppTest.from_file(str(APP), default_timeout=60)
    if view is not None:
        at.query_params["view"] = view
    at.run()
    _ok(at)
    return at


def test_bare_url_opens_home_with_live_figures(tmp_path, monkeypatch):
    at = _render(tmp_path, monkeypatch)
    page = _visible(at)
    assert at.session_state["br-view"] == "home"
    assert "Verifiable climate action, on Celo" in page and HERO in page and "proven on-chain." in page
    assert [b.label for b in at.button if b.key and b.key.startswith("br-cta")] == [
        "Register a tree  →", "See the live on-chain assets"]
    # The strip: network and contract from the connection, one tree from getTreeStats, the pilot's receipt.
    assert "Celo · 42220" in page and "Trees registered" in page and "0x04Db…84E64" in page
    assert "0.054 CELO" in page and "270,077 gas · 0.054 CELO" in page
    assert "Why this runs on Celo" in page and "eco-friendly, climate-aligned L1/L2" in page
    assert "carbon-negative" not in page
    assert "How a tree gets registered" in page
    assert PLANTER not in page and PROTOCOL not in page
    found = [j for j in JARGON if j.lower() in page.lower()]
    assert not found, found


@pytest.mark.parametrize("cta,view,marker", [("br-cta-register", "register", PLANTER),
                                             ("br-cta-protocol", "protocol", PROTOCOL)])
def test_calls_to_action_lead_into_the_demo(tmp_path, monkeypatch, cta, view, marker):
    at = _render(tmp_path, monkeypatch)
    at.button(key=cta).click().run()
    _ok(at)
    assert at.session_state["br-view"] == view and marker in _visible(at)
    assert at.query_params["view"] == [view]
    assert HERO not in _visible(at)


@pytest.mark.parametrize("value,view,marker", [
    ("home", "home", HERO), ("register", "register", PLANTER), ("protocol", "protocol", PROTOCOL),
    ("planter", "register", PLANTER), ("operator", "protocol", PROTOCOL),  # the published names, kept as aliases
    ("nonsense", "home", HERO),
])
def test_view_parameter_and_its_aliases(tmp_path, monkeypatch, value, view, marker):
    at = _render(tmp_path, monkeypatch, value)
    assert at.session_state["br-view"] == view
    assert marker in _visible(at)


def test_pilot_cost_falls_back_to_the_recorded_mint(tmp_path, monkeypatch):
    def unreachable(self, tx_hash):
        raise ConnectionError("rpc down")

    monkeypatch.setattr(PlanterChain, "get_receipt", unreachable)
    page = _visible(_render(tmp_path, monkeypatch))
    assert "270,077 gas · 0.054 CELO" in page
