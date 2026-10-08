"""The startup probe is cached by reference, never through pickle.

A hosted run raised st.cache_data's UnserializableReturnValueError at startup: "Cannot serialize the return value
(of type dashboard.chain.Probe) in probe_chain()". cache_data pickles what the function returns on the way into its
cache, and whether a Probe serializes is decided by the host's own web3/pickle build rather than by anything in this
repository, so the fix removes the serialization step: the probe is held as a resource, which stores the object by
reference. These tests pin that. The first one hands the app a probe result that refuses to pickle at all, which is
the reported failure: on cache_data the app never draws a view, on cache_resource it renders normally. The second
holds the 30 s window in place, so a widget click still never pays the round trips twice.
"""
import functools
from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from dashboard import chain as chain_mod
from dashboard import config
from dashboard.test_app_signing import OfflineChain
from dashboard.test_config import _key_env

APP = Path(__file__).resolve().parent / "app.py"


class Unpicklable:
    """A probe result that refuses to pickle, the way the hosted run's did."""

    def __init__(self, overview):
        self.rpc_chain = overview["boundChainId"]
        self.overview = overview
        self.is_verifier = False

    def __reduce_ex__(self, protocol):
        raise TypeError("cannot pickle 'Unpicklable' object")


class UnpicklableProbeChain(OfflineChain):
    def probe(self, budget_s=chain_mod.PROBE_BUDGET_S):
        return Unpicklable(self.overview())


def _render(tmp_path, monkeypatch, chain_cls, view="home"):
    _key_env(tmp_path, monkeypatch)
    monkeypatch.setattr(chain_mod, "Chain", chain_cls)
    monkeypatch.setattr(config, "load_settings", functools.partial(config.load_settings, tmp_path, secrets={}))
    st.cache_resource.clear()
    st.cache_data.clear()
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.query_params["view"] = view
    at.run()
    return at


def test_an_unpicklable_probe_still_draws_the_view(tmp_path, monkeypatch):
    """The reported crash: a probe result the host cannot serialize must not cost the page its view."""
    at = _render(tmp_path, monkeypatch, UnpicklableProbeChain)
    assert not at.exception, [e.value for e in at.exception]
    assert any("br-hero" in str(m.value) for m in at.markdown), "the home view is drawn"
    assert not at.warning and not at.error, [w.value for w in at.warning] + [e.value for e in at.error]
    assert not [b for b in at.button if b.key == "br-retry"], "no retry frame"


def test_the_probe_is_read_once_per_cache_window(tmp_path, monkeypatch):
    calls = []

    class CountingProbeChain(OfflineChain):
        def probe(self, budget_s=chain_mod.PROBE_BUDGET_S):
            calls.append(budget_s)
            return super().probe(budget_s)

    at = _render(tmp_path, monkeypatch, CountingProbeChain)
    assert not at.exception, [e.value for e in at.exception]
    at.run()  # the rerun a widget click makes
    assert len(calls) == 1, calls
