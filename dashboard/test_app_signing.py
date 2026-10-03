"""The page renders the chain telemetry whatever PRIVATE_KEY holds: a malformed key turns signing off, it does
not blank the page. The chain is stubbed below the read calls, so this runs offline; load_settings is the real
one, reading PRIVATE_KEY from the process environment the way the hosted app does."""
import functools
import logging
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from dashboard import chain as chain_mod
from dashboard import config, h3_nullifier
from dashboard.chain import MintRecord, TbaCheck, TreeStats
from dashboard.test_config import BAD_KEYS, HEX64, MAINNET, _key_env

APP = Path(__file__).resolve().parent / "app.py"
BLOCK = 31_337_421
ZERO = "0x" + "00" * 20
# The app's own form defaults: lat -1.2921, lng 36.8219, salt "plot-1". That plot is the tree live on Celo
# mainnet as token 1, minted 1 October 2026, so its nullifier is active and minting it again reverts. The
# offline chain below models that state, and not the pre-mint one: an alive tree whose nullifier is inactive
# is a state the contract cannot reach (mintTree sets both, only reportMortality clears the nullifier), so
# asserting against it would test a world that does not exist and would hide the verdict the live app shows.
PILOT = h3_nullifier.derive(-1.2921, 36.8219, "plot-1", h3_nullifier.DEFAULT_RESOLUTION).nullifier


class OfflineChain(chain_mod.Chain):
    """The real Chain (settings, signer, proxy) with every RPC read answered locally."""

    def rpc_chain_id(self):
        return self.settings.chain_id

    def signer_is_verifier(self):
        return bool(self.signer)

    def overview(self):
        return {"name": "BioRig", "symbol": "TREE", "paused": False, "registry": ZERO, "implementation": ZERO,
                "boundChainId": self.settings.chain_id, "bufferPool": ZERO, "block": BLOCK}

    def core_implementation(self):
        return ZERO

    def is_nullifier_active(self, nullifier):
        return bytes(nullifier) == PILOT

    def get_tree_stats(self, token_id):
        return TreeStats(10, 20, 1_790_893_247, ZERO, True, PILOT)

    def find_mint(self, token_id, chunk=5_000):
        return MintRecord(token_id, "0x" + "11" * 32, BLOCK - 10, ZERO, b"\x01" * 32, ZERO)

    def check_tba(self, token_id, record=None):
        return TbaCheck(ZERO, ZERO, ZERO, (self.settings.chain_id, self.proxy, token_id), True)

    def owner_of(self, token_id):
        return ZERO

    def token_uri(self, token_id):
        return ""

    def get_receipt(self, tx_hash):
        """The pilot registration's receipt (DEPLOY.md: 270,077 gas at 200.0011 gwei), read by the home view."""
        return {"gasUsed": 270_077, "effectiveGasPrice": 200_001_100_000}

    def simulate_mint(self, planter, nullifier, dbh, biomass):
        """mintTree's own rule (src/BioRigCoreV5.sol): an active nullifier reverts, any other one succeeds."""
        if bytes(nullifier) == PILOT:
            return chain_mod.Simulation(False, None, None, "NullifierInUse()", self.signer, "0x")
        return chain_mod.Simulation(True, 2, 210_000, None, self.signer, "0x")


def _render(tmp_path, monkeypatch, key):
    _key_env(tmp_path, monkeypatch)
    if key is not None:
        monkeypatch.setenv("PRIVATE_KEY", key)
    monkeypatch.setattr(chain_mod, "Chain", OfflineChain)
    monkeypatch.setattr(config, "load_settings", functools.partial(config.load_settings, tmp_path, secrets={}))
    st.cache_resource.clear()
    st.cache_data.clear()
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.query_params["view"] = "operator"  # the published alias of protocol, the panel these tests read
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _rendered(at) -> list[str]:
    kinds = ("markdown", "caption", "warning", "error", "info", "success", "subheader", "title", "exception")
    texts = [str(e.value) for kind in kinds for e in getattr(at, kind)]
    texts += [str(w.value) for w in at.text_input]
    return texts


def _assert_telemetry(at):
    page = "\n".join(_rendered(at))
    assert f"{BLOCK:,}" in page and "Celo mainnet" in page  # the status bar
    assert "Live state · getTreeStats(1)" in page and "derivations agree" in page  # right-hand read path
    assert not [e.value for e in at.error], "no error on a read-only render"
    assert "Could not reach the chain" not in page


def test_absent_key_renders_read_only(tmp_path, monkeypatch):
    at = _render(tmp_path, monkeypatch, None)
    _assert_telemetry(at)
    assert [w.value for w in at.warning] == ["PRIVATE_KEY is not set in .env, so the verifier account is unavailable."]
    page = "\n".join(_rendered(at))
    assert "signer <span class=\"mono\">none</span>" in page and "no VERIFIER_ROLE" in page


@pytest.mark.parametrize("key", [HEX64, "0x" + HEX64], ids=["bare", "0x"])
def test_valid_key_signs(tmp_path, monkeypatch, key):
    at = _render(tmp_path, monkeypatch, key)
    _assert_telemetry(at)
    assert not at.warning
    page = "\n".join(_rendered(at))
    assert "VERIFIER_ROLE ✓" in page and "would revert" in page and "NullifierInUse()" in page
    assert HEX64 not in page.lower()


def test_fresh_salt_in_the_pilot_cell_still_simulates(tmp_path, monkeypatch):
    """The other half of the same live rule: a salt the chain has not seen is a nullifier it will accept."""
    at = _render(tmp_path, monkeypatch, HEX64)
    labels = [w.label for w in at.text_input]
    assert labels == ["planter", "salt"], labels
    at.text_input[1].set_value("offline-fresh-salt").run()
    assert not at.exception, [e.value for e in at.exception]
    page = "\n".join(_rendered(at))
    assert "would succeed" in page and "would revert" not in page


@pytest.mark.parametrize("label,raw,length,index", BAD_KEYS, ids=[b[0] for b in BAD_KEYS])
def test_invalid_key_disables_signing_and_still_renders(tmp_path, monkeypatch, caplog, capsys,
                                                        label, raw, length, index):
    caplog.set_level(logging.DEBUG)
    at = _render(tmp_path, monkeypatch, raw)
    _assert_telemetry(at)
    warnings = [w.value for w in at.warning]
    assert len(warnings) == 1, warnings
    assert warnings[0].startswith("Signing disabled") and f"{length} characters" in warnings[0]
    if index is not None:
        assert f"index {index}" in warnings[0]
    page = "\n".join(_rendered(at))
    assert "signer <span class=\"mono\">none</span>" in page and "no VERIFIER_ROLE" in page
    assert "codec" not in page and "ordinal" not in page
    out = capsys.readouterr()
    for text in (page, caplog.text, out.out, out.err, repr(at.session_state)):
        assert HEX64 not in text.lower() and raw not in text and "ء" not in text
