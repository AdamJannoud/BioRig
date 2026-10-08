"""BioRig demo dashboard. A home screen first; the three-step planter flow and the technical panel one click away.

    .venv/bin/streamlit run dashboard/app.py

Three views, switched by the Home / Register / Protocol control in the header or by ?view=:
  home      the default (dashboard/home_view.py): what BioRig is, why Celo, the live figures, two calls to action
  register  the three-step planter flow (dashboard/planter_view.py)
  protocol  the protocol telemetry, the eth_call simulation and the TBA cross-check (dashboard/operator_view.py)
The older ?view=planter and ?view=operator are published in the proposal and the deployment docs, so they stay
accepted as aliases of register and protocol. Every view reads the same chain connection, and every word on screen
comes from dashboard/strings.py.

Nothing touches the network before the header and the view control are on screen: the first reads of the chain run
after them, under a spinner and inside chain.PROBE_BUDGET_S. A chain that is down or slow leaves the frame up with
the reason and a Retry button, never a blank page.

The verifier key is read from .env on the server and never sent to the browser: every signature happens
in this Python process.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard import home_view, operator_view, planter_view, ui  # noqa: E402
from dashboard.chain import PROBE_BUDGET_S, Chain, Probe, ProbeTimeout  # noqa: E402
from dashboard.config import (ChainSelectionError, PrivateKeyError, ProxyResolutionError,  # noqa: E402
                              load_settings)
from dashboard.strings import t  # noqa: E402

st.set_page_config(page_title=t("page.title"), page_icon=str(ui.FAVICON), layout="wide")
ui.install_theme()

VIEWS = ("home", "register", "protocol")
VIEW_ALIASES = {"planter": "register", "operator": "protocol"}  # the published names, kept working


def initial_view(requested: str | None) -> str:
    """The view a ?view= value opens: a current name, an alias of one, else home."""
    view = VIEW_ALIASES.get(requested or "", requested)
    return view if view in VIEWS else "home"


# --------------------------------------------------------------------------- connection

@st.cache_resource(show_spinner=False)
def get_chain() -> tuple[Chain, str | None]:
    """The chain, and why signing is off when PRIVATE_KEY was set but rejected. Signing is optional: a bad key
    drops to read-only here, so it can never take the telemetry down with it. No network: this only builds the
    provider, so it is safe before the first paint."""
    try:
        return Chain(load_settings()), None
    except PrivateKeyError as exc:
        return Chain(exc.settings), str(exc)


@st.cache_resource(ttl=30, show_spinner=False)
def probe_chain(_chain: Chain, rpc_url: str, chain_id: int, proxy: str, signer: str | None) -> Probe:
    """chain id, overview and verifier role, bounded by PROBE_BUDGET_S. Cached for 30 s so a widget click does not
    pay eleven round trips again; a raised error is not memoised, so the next run (or Retry) asks afresh.

    Held as a resource, not in the data cache: cache_data pickles what a function returns on the way in, and a hosted
    run raised UnserializableReturnValueError for Probe, which left every view on the retry frame. Whether a Probe
    serializes is decided by the host's own web3/pickle build, so the fix is to stop serializing it: a resource is
    kept by reference. The value is chain state read once per window and never mutated."""
    return _chain.probe(PROBE_BUDGET_S)


def _retry() -> None:
    get_chain.clear()
    probe_chain.clear()


def _unavailable(message: str, detail: str | None = None, alert=st.warning) -> None:
    """The calm stand-in for a view when there is no chain to read: the reason and a way to ask again."""
    alert(message)
    if detail:
        st.caption(detail)
    st.button(t("chain.retry"), key="br-retry", on_click=_retry)  # the click itself reruns the script
    ui.credit()
    st.stop()


def _short(exc: Exception) -> str:
    """One line of an RPC error. A transport error is named by its type (ConnectTimeout, ConnectionError):
    requests' messages run to several hundred characters of pool internals and object addresses."""
    if isinstance(exc, OSError):
        return type(exc).__name__
    text = " ".join(str(exc).split()) or type(exc).__name__
    return text if len(text) <= 180 else text[:179] + "…"


# --------------------------------------------------------------------------- header + view toggle

def _view_changed() -> None:
    st.query_params["view"] = st.session_state["br-view"]


if "br-view" not in st.session_state:
    st.session_state["br-view"] = initial_view(st.query_params.get("view"))

try:
    chain, key_problem = get_chain()
    config_problem = None
except (ChainSelectionError, ProxyResolutionError) as exc:
    chain, key_problem, config_problem = None, None, str(exc)

if chain is not None:
    st.set_page_config(page_title=t("page.title_chain", chain=chain.settings.chain_name))

bar, toggle = st.columns([3, 2], vertical_alignment="center")
with bar:
    head = st.empty()  # painted now, repainted with the paused state once the chain has answered
    ui.header(chain.settings.chain_name if chain else None, False, target=head)
with toggle:
    view = st.segmented_control(t("view.label"), VIEWS, key="br-view", required=True, on_change=_view_changed,
                                format_func=lambda v: t("view." + v))

if config_problem is not None:
    _unavailable(config_problem, alert=st.error)  # a settings fault: its own message says what to fix

settings = chain.settings
try:
    with st.spinner(t("connecting")):
        probe = probe_chain(chain, settings.rpc_url, settings.chain_id, chain.proxy, chain.signer)
except ProbeTimeout as exc:
    _unavailable(t("chain.slow", seconds=f"{PROBE_BUDGET_S:g}"), t("chain.reason", rpc=settings.rpc_url,
                                                                   error="no answer"))
except Exception as exc:  # RPC down, wrong chain: say so beside the frame rather than leave a blank page
    _unavailable(t("chain.unreachable"), t("chain.reason", rpc=settings.rpc_url, error=_short(exc)))

rpc_chain, overview, is_verifier = probe.rpc_chain, probe.overview, probe.is_verifier
ui.header(settings.chain_name, overview["paused"], target=head)

if view == "protocol":
    operator_view.render(chain, rpc_chain, overview, is_verifier, key_problem)
elif view == "register":
    planter_view.render(chain, overview, key_problem)
else:
    home_view.render(chain)
ui.credit()
