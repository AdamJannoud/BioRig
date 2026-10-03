"""BioRig demo dashboard. A home screen first; the three-step planter flow and the technical panel one click away.

    .venv/bin/streamlit run dashboard/app.py

Three views, switched by the Home / Register / Protocol control in the header or by ?view=:
  home      the default (dashboard/home_view.py): what BioRig is, why Celo, the live figures, two calls to action
  register  the three-step planter flow (dashboard/planter_view.py)
  protocol  the protocol telemetry, the eth_call simulation and the TBA cross-check (dashboard/operator_view.py)
The older ?view=planter and ?view=operator are published in the proposal and the deployment docs, so they stay
accepted as aliases of register and protocol. Every view reads the same chain connection, and every word on screen
comes from dashboard/strings.py.

The verifier key is read from .env on the server and never sent to the browser: every signature happens
in this Python process.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard import home_view, operator_view, planter_view, ui  # noqa: E402
from dashboard.chain import Chain  # noqa: E402
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

@st.cache_resource(show_spinner=t("connecting"))
def get_chain() -> tuple[Chain, str | None]:
    """The chain, and why signing is off when PRIVATE_KEY was set but rejected. Signing is optional: a bad key
    drops to read-only here, so it can never take the telemetry down with it."""
    try:
        return Chain(load_settings()), None
    except PrivateKeyError as exc:
        return Chain(exc.settings), str(exc)


try:
    chain, key_problem = get_chain()
    settings = chain.settings
    rpc_chain = chain.assert_chain()
    overview = chain.overview()
    is_verifier = chain.signer_is_verifier()
except (ChainSelectionError, ProxyResolutionError) as exc:
    st.error(str(exc))
    st.stop()
except Exception as exc:  # RPC down, wrong chain: show it rather than a blank page
    st.error(t("chain.unreachable", error=exc))
    st.stop()

st.set_page_config(page_title=t("page.title_chain", chain=settings.chain_name))


# --------------------------------------------------------------------------- header + view toggle

def _view_changed() -> None:
    st.query_params["view"] = st.session_state["br-view"]


if "br-view" not in st.session_state:
    st.session_state["br-view"] = initial_view(st.query_params.get("view"))

bar, toggle = st.columns([3, 2], vertical_alignment="center")
with bar:
    ui.header(settings.chain_name, overview["paused"])
with toggle:
    view = st.segmented_control(t("view.label"), VIEWS, key="br-view", required=True, on_change=_view_changed,
                                format_func=lambda v: t("view." + v))

if view == "protocol":
    operator_view.render(chain, rpc_chain, overview, is_verifier, key_problem)
elif view == "register":
    planter_view.render(chain, overview, key_problem)
else:
    home_view.render(chain)
ui.credit()
