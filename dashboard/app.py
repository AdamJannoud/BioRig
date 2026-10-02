"""BioRig demo dashboard. A three-step planter flow by default; the technical panel one click away.

    .venv/bin/streamlit run dashboard/app.py

?view=operator opens the operator view directly (the protocol telemetry, the eth_call simulation and the TBA
cross-check; dashboard/operator_view.py). The default is the planter flow (dashboard/planter_view.py). Both views
read the same chain connection, and every word on screen comes from dashboard/strings.py.

The verifier key is read from .env on the server and never sent to the browser: every signature happens
in this Python process.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard import operator_view, planter_view, ui  # noqa: E402
from dashboard.chain import Chain  # noqa: E402
from dashboard.config import (ChainSelectionError, PrivateKeyError, ProxyResolutionError,  # noqa: E402
                              load_settings)
from dashboard.strings import t  # noqa: E402

st.set_page_config(page_title=t("page.title"), page_icon=str(ui.FAVICON), layout="wide")
ui.install_theme()

VIEWS = ("planter", "operator")


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
    st.session_state["br-view"] = "operator" if st.query_params.get("view") == "operator" else "planter"

bar, toggle = st.columns([5, 2], vertical_alignment="center")
with bar:
    ui.header(settings.chain_name, overview["paused"])
with toggle:
    view = st.segmented_control(t("view.label"), VIEWS, key="br-view", required=True, on_change=_view_changed,
                                format_func=lambda v: f'{t("view.label")}: {t("view." + v).lower()}'
                                if v == st.session_state.get("br-view") else t("view." + v))

if view == "operator":
    operator_view.render(chain, rpc_chain, overview, is_verifier, key_problem)
else:
    planter_view.render(chain, overview, key_problem)
ui.credit()
