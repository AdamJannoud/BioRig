"""The planter flow, offline: three steps, plain words, the pre-flight check's two outcomes, and the read-only stop.

The chain is the same offline model test_app_signing.py uses (the pilot plot is minted as token 1, any other plot is
free), so the verdicts asserted here are the ones the live chain gives for the same inputs."""
import functools
import html
import re
from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from dashboard import chain as chain_mod
from dashboard import config, planter_view, strings
from dashboard.test_app_signing import HEX64, OfflineChain
from dashboard.test_config import _key_env

APP = Path(__file__).resolve().parent / "app.py"
# Protocol terms the plan moves out of the planter flow (they stay in the operator view).
JARGON = ("spatialNullifier", "nullifier", "keccak", "eth_call", "VERIFIER_ROLE", "H3 res", "salt", "NullifierInUse",
          "tbaAddress", "TBA", "CREATE2", "mintTree", "initialDBH", "initialBiomass", "uint96", "would revert",
          "implementation slot", "ERC-1967", "preimage")


class PlanterChain(OfflineChain):
    sent = []

    def get_tree_stats(self, token_id):
        if token_id > 1:
            raise RuntimeError("execution reverted")
        return super().get_tree_stats(token_id)

    def gas_price_wei(self):
        return 25 * 10**9

    def send_mint(self, *args, **kwargs):
        PlanterChain.sent.append(args)
        raise AssertionError("the planter tests never broadcast")


def _render(tmp_path, monkeypatch, key=HEX64, allow_mint=None):
    _key_env(tmp_path, monkeypatch)
    if key is not None:
        monkeypatch.setenv("PRIVATE_KEY", key)
    if allow_mint is not None:
        monkeypatch.setenv("ALLOW_MINT", allow_mint)
    monkeypatch.setattr(chain_mod, "Chain", PlanterChain)
    monkeypatch.setattr(config, "load_settings", functools.partial(config.load_settings, tmp_path, secrets={}))
    st.cache_resource.clear()
    st.cache_data.clear()
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.query_params["view"] = "register"  # the bare URL opens home (dashboard/test_home_view.py)
    at.run()
    _ok(at)
    return at


def _ok(at):
    assert not at.exception, [e.value for e in at.exception]


def _page(at) -> str:
    kinds = ("markdown", "caption", "warning", "error", "info", "success", "subheader")
    texts = [str(e.value) for kind in kinds for e in getattr(at, kind)]
    texts += [w.label for w in at.text_input] + [b.label for b in at.button]
    return "\n".join(texts)


def _visible(at) -> str:
    """The page's words without HTML tags or the theme CSS block (class names are not wording)."""
    text = re.sub(r"<style>.*?</style>", "", _page(at), flags=re.S)
    text = re.sub(r"<svg.*?</svg>", "", text, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", text))


def _click(at, key):
    at.button(key=key).click().run()
    _ok(at)


def _no_jargon(at):
    words = _visible(at)
    found = [j for j in JARGON if j.lower() in words.lower()]
    assert not found, found


def test_register_view_opens_on_step_one_with_the_computed_biomass(tmp_path, monkeypatch):
    at = _render(tmp_path, monkeypatch)
    page = _visible(at)
    assert "How thick is the trunk?" in page and "Measure tree" in page and "Celo mainnet" in page
    assert at.slider(key="p_dbh").value == 24
    assert "208" in page and "98" in page and "359" in page  # biomass, carbon, CO2e for 24 cm
    assert "Chave et al. 2014" in page
    assert "Register a tree" not in page  # the protocol panel and home are one click away, not on this view
    _no_jargon(at)


def test_slider_drives_the_numbers(tmp_path, monkeypatch):
    at = _render(tmp_path, monkeypatch)
    at.slider(key="p_dbh").set_value(10).run()
    _ok(at)
    assert "20 <small>kg</small>" in _page(at)  # the pilot tree: 10 cm -> 19.9 kg


def test_locate_step_says_whether_the_plot_is_free(tmp_path, monkeypatch):
    at = _render(tmp_path, monkeypatch)
    _click(at, "p_next1")
    page = _visible(at)
    assert "Where is the tree?" in page
    assert "This plot is free." in page  # the default is the first free plot in the pilot cell
    assert "-1.292100, 36.821900" in page and "≈307 m²" in _page(at)  # the map caption
    _no_jargon(at)
    at.text_input(key="p_ref").set_value("plot-1").run()  # the pilot plot, token 1
    _ok(at)
    assert "This plot already has a tree registered on it." in _visible(at)
    at.text_input(key="p_ref").set_value("north field, tree 3").run()
    _ok(at)
    assert "This plot is free." in _visible(at)


def test_step_values_survive_moving_between_steps(tmp_path, monkeypatch):
    at = _render(tmp_path, monkeypatch)
    at.slider(key="p_dbh").set_value(37).run()
    _click(at, "p_next1")
    _click(at, "p_next2")
    assert "37 cm" in _visible(at)
    _click(at, "p_back3")
    _click(at, "p_back2")
    assert at.slider(key="p_dbh").value == 37


def test_check_on_a_taken_plot_reads_not_this_one(tmp_path, monkeypatch):
    at = _render(tmp_path, monkeypatch)
    _click(at, "p_next1")
    at.text_input(key="p_ref").set_value("plot-1").run()  # the pilot plot, token 1
    _click(at, "p_next2")
    page = _visible(at)
    assert "Claim & register" in page and "nothing costs anything" in page
    _click(at, "p_check_btn")
    page = _visible(at)
    assert "Not this one." in page and "This plot already has a tree registered on it." in page
    assert "Ready." not in page
    _no_jargon(at)


def test_check_on_a_free_plot_is_ready_and_the_public_demo_stops_there(tmp_path, monkeypatch):
    at = _render(tmp_path, monkeypatch, allow_mint="false")
    _click(at, "p_next1")
    at.text_input(key="p_ref").set_value("offline-fresh").run()
    _click(at, "p_next2")
    _click(at, "p_check_btn")
    page = _visible(at)
    assert "Ready." in page and "#2" in page and "0.00525 CELO" in page  # 210,000 gas x 25 gwei
    assert "Registration is not enabled on this demo." in page
    assert not [b for b in at.button if b.key == "p_register"]
    assert "worked out by the check" not in page  # the tree smart wallet is now derived
    _no_jargon(at)


def test_default_plot_is_the_first_free_one_and_its_check_reads_ready(tmp_path, monkeypatch):
    at = _render(tmp_path, monkeypatch, allow_mint="false")
    assert at.session_state["p_ref"] == "plot-2"  # plot-1 in the pilot cell is token 1
    _click(at, "p_next1")
    assert "The pilot plot (Nairobi)" in _visible(at) and "This plot is free." in _visible(at)
    _click(at, "p_next2")
    _click(at, "p_check_btn")
    page = _visible(at)
    assert "Ready." in page and "Not this one." not in page
    assert "Registration is not enabled on this demo." in page and not [b for b in at.button if b.key == "p_register"]


def test_default_reference_walks_the_candidates_in_order():
    taken = {planter_view.h3_nullifier.derive(planter_view.PILOT["lat"], planter_view.PILOT["lng"], r, 12).nullifier
             for r in ("plot-1", "plot-2", "plot-3")}
    asked = []

    def is_active(n):
        asked.append(n)
        return bytes(n) in taken

    assert planter_view.default_reference(is_active) == "plot-4" and len(asked) == 4
    assert planter_view.default_reference(lambda n: True) == planter_view.DEFAULT_REFERENCE  # every candidate taken


def test_default_reference_falls_back_to_the_pilot_plot_offline(tmp_path, monkeypatch):
    def unreachable(n):
        raise ConnectionError("rpc down")

    assert planter_view.default_reference(unreachable) == planter_view.DEFAULT_REFERENCE == "plot-1"
    monkeypatch.setattr(PlanterChain, "is_nullifier_active", lambda self, n: unreachable(n))
    at = _render(tmp_path, monkeypatch)  # the flow still renders, on today's pilot default
    assert at.session_state["p_ref"] == "plot-1"
    assert "How thick is the trunk?" in _visible(at)


def test_register_control_only_where_minting_is_on_and_never_pressed(tmp_path, monkeypatch):
    PlanterChain.sent.clear()
    at = _render(tmp_path, monkeypatch, allow_mint="true")
    _click(at, "p_next1")
    at.text_input(key="p_ref").set_value("offline-fresh").run()
    _click(at, "p_next2")
    _click(at, "p_check_btn")
    register = at.button(key="p_register")
    assert register.label == "Register this tree on Celo" and register.disabled  # needs the confirm box first
    assert PlanterChain.sent == []


def test_without_an_account_the_check_cannot_run(tmp_path, monkeypatch):
    at = _render(tmp_path, monkeypatch, key=None)
    _click(at, "p_next1")
    _click(at, "p_next2")
    assert at.button(key="p_check_btn").disabled
    assert "Read-only — you can look, not register." in _visible(at)


def test_start_over_resets_the_flow(tmp_path, monkeypatch):
    at = _render(tmp_path, monkeypatch)
    at.slider(key="p_dbh").set_value(60).run()
    _click(at, "p_next1")
    _click(at, "p_next2")
    _click(at, "p_reset")
    assert at.slider(key="p_dbh").value == planter_view.DEFAULT_DBH


def test_live_tree_badges(tmp_path, monkeypatch):
    at = _render(tmp_path, monkeypatch)
    page = _page(at)
    assert "Tree #1" in page and "10 cm · 20 kg" in page and "/instance/1" in page and "Tree #2" not in page


def test_protocol_view_is_one_click_away(tmp_path, monkeypatch):
    at = _render(tmp_path, monkeypatch)
    at.button_group(key="br-view").set_value("protocol").run()
    _ok(at)
    page = _page(at)
    assert "Register a tree" in page and "spatialNullifier" in page and "How thick is the trunk?" not in page


def test_planter_wording_is_plain():
    found = {k: [j for j in JARGON if j.lower() in v.lower()] for k, v in strings.EN.items() if not k.startswith("op.")}
    assert not {k: v for k, v in found.items() if v}


def test_plot_size_width():
    assert round(planter_view.across_m(307)) == 19
