"""The dashboard's startup can never hang on an unreachable RPC.

On a cold host the first script run read the chain before drawing anything, and with web3's default of five
retries at a 30 s timeout one unreachable call blocked for 152 s: the hosted demo showed a blank page. These tests
point the chain at a non-routable address (10.255.255.1 drops packets, so a connect waits for its timeout) and hold
every read to a wall-clock bound far under that. Each bound is enforced from outside the call with a worker thread,
so the old code fails at the bound rather than after 152 s. The app-level tests stub the chain and run offline.
"""
import functools
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from dashboard import chain as chain_mod
from dashboard import config, ui
from dashboard.test_app_signing import OfflineChain
from dashboard.test_config import _key_env

APP = Path(__file__).resolve().parent / "app.py"
BLACKHOLE = "http://10.255.255.1:8545"
CALL_BOUND_S = 15  # one RPC call: RPC_TIMEOUT_S plus slack; the old code took 152 s


@pytest.fixture
def blackhole_chain(tmp_path, monkeypatch):
    _key_env(tmp_path, monkeypatch)
    monkeypatch.setenv("RPC_URL", BLACKHOLE)
    settings = config.load_settings(tmp_path, secrets={})
    assert settings.rpc_url == BLACKHOLE
    return chain_mod.Chain(settings)


def _within(fn, bound_s):
    """fn()'s outcome (value or raised exception) and its elapsed time, or a failure if it outlives bound_s."""
    pool = ThreadPoolExecutor(max_workers=1)
    start = time.monotonic()
    future = pool.submit(fn)
    try:
        try:
            outcome = future.result(timeout=bound_s)
        except FutureTimeout:
            if not future.done():  # FutureTimeout is the builtin TimeoutError, which ProbeTimeout also is
                pytest.fail(f"still blocked after {bound_s} s")
            outcome = future.exception()
        except Exception as exc:  # an unreachable RPC is expected to raise; what matters is that it returns
            outcome = exc
        return outcome, time.monotonic() - start
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def test_provider_makes_one_bounded_attempt(blackhole_chain):
    provider = blackhole_chain.w3.provider
    assert provider.exception_retry_configuration.retries == 1
    assert provider.get_request_kwargs()["timeout"] <= 10


def test_unreachable_rpc_call_returns_within_bound(blackhole_chain):
    outcome, elapsed = _within(blackhole_chain.assert_chain, CALL_BOUND_S)
    assert isinstance(outcome, chain_mod._TRANSIENT), repr(outcome)  # ConnectTimeout, or a refusal if quicker
    assert elapsed < CALL_BOUND_S


def test_startup_probe_honours_its_budget(blackhole_chain):
    outcome, elapsed = _within(lambda: blackhole_chain.probe(budget_s=1.0), 5)
    assert isinstance(outcome, (chain_mod.ProbeTimeout, *chain_mod._TRANSIENT)), repr(outcome)
    assert elapsed < 3


# --------------------------------------------------------------------------- the app keeps its frame

class DownChain(OfflineChain):
    def rpc_chain_id(self):
        raise ConnectionError("HTTPConnectionPool(host='10.255.255.1', port=8545): Max retries exceeded")


class SlowChain(OfflineChain):
    def rpc_chain_id(self):
        time.sleep(6)
        return super().rpc_chain_id()


def _render(tmp_path, monkeypatch, chain_cls, view="home"):
    _key_env(tmp_path, monkeypatch)
    monkeypatch.setattr(chain_mod, "Chain", chain_cls)
    monkeypatch.setattr(config, "load_settings", functools.partial(config.load_settings, tmp_path, secrets={}))
    st.cache_resource.clear()
    st.cache_data.clear()
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.query_params["view"] = view
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _assert_frame_with_retry(at, wording):
    assert any("br-appbar" in str(m.value) for m in at.markdown), "the header is drawn"
    assert at.session_state["br-view"] in ("home", "register", "protocol")
    assert [w.value for w in at.warning] and wording in at.warning[0].value
    assert at.button(key="br-retry").label == "Retry"
    assert not at.error


@pytest.mark.parametrize("view", ["home", "register", "protocol"])
def test_unreachable_chain_keeps_the_frame_and_offers_retry(tmp_path, monkeypatch, view):
    at = _render(tmp_path, monkeypatch, DownChain, view)
    _assert_frame_with_retry(at, "Could not reach the chain")
    assert any("ConnectionError" in str(c.value) for c in at.caption)  # named, not dumped

    # The RPC comes back: Retry drops the cached chain and the next run renders the view.
    monkeypatch.setattr(chain_mod, "Chain", OfflineChain)
    at.button(key="br-retry").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert not at.warning or "Could not reach" not in at.warning[0].value
    assert not [b for b in at.button if b.key == "br-retry"]


def test_slow_chain_stops_at_the_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(chain_mod, "PROBE_BUDGET_S", 0.5)
    start = time.monotonic()
    at = _render(tmp_path, monkeypatch, SlowChain)
    assert time.monotonic() - start < 4  # the 6 s read was abandoned at the 0.5 s budget
    _assert_frame_with_retry(at, "taking longer than 0.5 s")


def test_mode_script_cannot_feed_its_own_observer():
    """The browser half of the same hang: MODE_JS observes body's dir and also writes it. A write queues a mutation
    even when the value is unchanged, so every write must be guarded or the page's main thread spins forever."""
    writes = [line for line in ui.MODE_JS.splitlines() if "'dir'" in line and "setAttribute" in line
              or "style.direction =" in line]
    assert writes and all("!==" in line for line in writes), writes


def test_mode_script_reports_the_language_the_slider_lays_itself_out_in():
    """Streamlit's slider takes its writing direction from react-aria, and react-aria reads the BROWSER's locale, not
    the page's dir/lang that MODE_JS pins. In an Arabic-language browser the handle and its value label were therefore
    laid out at 100 - percent while the track's fill stayed at percent: the desync reported on the trunk slider.
    MODE_JS must report the language the UI is actually written in and let the widget re-read it."""
    assert "'language'" in ui.MODE_JS
    assert "'en-US'" in ui.MODE_JS
    assert "languagechange" in ui.MODE_JS
