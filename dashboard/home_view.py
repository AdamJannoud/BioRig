"""Home: the first screen. What BioRig is, why it runs on Celo, and the two ways into the demo.

The only screen allowed a marketing register (the planter flow keeps its plain words, the protocol view its protocol
terms). Every figure on it is read from the chain at load: the network and contract from the connection, the tree
count from the same getTreeStats walk the planter flow's badges use, and the pilot registration's cost from the
mint's own receipt. The artwork is the brand kit as committed (mark, wordmark, the plot-grid motif); nothing new.

The two calls to action switch the "br-view" control app.py draws, so the branch stays reversible from any screen.
"""
from __future__ import annotations

import html

import streamlit as st

from dashboard.chain import Chain, short_hex
from dashboard.planter_view import live_trees
from dashboard.strings import t
from dashboard.ui import inline_svg

# The pilot registration: token 1 on Celo mainnet, 1 October 2026 (DEPLOY.md, "first mainnet mint"). Its cost is read
# from that receipt; the recorded figures stand in only where the receipt cannot be read (another chain, RPC down).
PILOT_MINT_TX = {42220: "0x70476c02ef1af918a213eec63472e6cdbabcedd50193cdd6a7a89a09527797f7"}
PILOT_RECORDED = (270_077, 54_015_697_000_000_000)  # gas used, fee in wei: block 78992489


@st.cache_data(ttl=3600, show_spinner=False)
def pilot_cost(_chain: Chain, chain_id: int) -> tuple[int, int]:
    """(gas used, fee in wei) of the pilot registration."""
    tx = PILOT_MINT_TX.get(chain_id)
    if tx:
        try:
            receipt = _chain.get_receipt(tx)
            gas = int(receipt["gasUsed"])
            return gas, gas * int(receipt["effectiveGasPrice"])
        except Exception:  # noqa: BLE001 - the recorded figure is the same mint's
            pass
    return PILOT_RECORDED


def _celo(wei: int) -> str:
    return f"{wei / 10**18:.2g}"


def _go(view: str) -> None:
    st.session_state["br-view"] = view
    st.query_params["view"] = view


def _bold(text: str) -> str:
    """**bold** in the wording becomes <em>, the accented half of the headline."""
    parts = html.escape(text).split("**")
    return "".join(f"<em>{p}</em>" if i % 2 else p for i, p in enumerate(parts))


def _kpi(label: str, value: str, cls: str = "") -> str:
    return (f'<div class="br-kpi"><div class="lab">{html.escape(t(label))}</div>'
            f'<div class="v {cls}">{html.escape(value)}</div></div>')


def render(chain: Chain) -> None:
    settings = chain.settings
    trees = live_trees(chain, settings.chain_id, chain.proxy)
    gas, fee_wei = pilot_cost(chain, settings.chain_id)
    fee = _celo(fee_wei)

    with st.container(key="br-hero"):
        st.markdown(
            '<div class="br-hero-lockup">'
            + inline_svg("mark.svg", "br-mark-light") + inline_svg("mark-reverse.svg", "br-mark-dark")
            + '<span class="br-wordmark">BioRig<span class="dot">.</span></span></div>'
            f'<div class="br-kicker">{html.escape(t("home.kicker"))}</div>'
            f'<h1 class="br-h1">{_bold(t("home.title"))}</h1>'
            f'<p class="br-sub">{html.escape(t("home.sub"))}</p>',
            unsafe_allow_html=True,
        )
        with st.container(horizontal=True, gap="small", key="br-ctas"):
            st.button(t("home.cta_register"), type="primary", key="br-cta-register", on_click=_go, args=("register",))
            st.button(t("home.cta_protocol"), key="br-cta-protocol", on_click=_go, args=("protocol",))
        st.markdown(
            '<div class="br-strip">'
            + _kpi("home.kpi.network", t("home.kpi.network_value", chain_id=settings.chain_id))
            + _kpi("home.kpi.trees", f"{len(trees):,}")
            + _kpi("home.kpi.pilot", t("home.kpi.pilot_value", fee=fee), "gold")
            + _kpi("home.kpi.contract", short_hex(chain.proxy, 4, 5))
            + "</div>",
            unsafe_allow_html=True,
        )

    cards = "".join(
        f'<div class="br-card"><div class="ic">0{n}</div>'
        f'<div class="tt">{html.escape(t(f"home.why.{n}.title"))}</div>'
        f'<p>{html.escape(t(f"home.why.{n}.body", fee=fee) if n == 3 else t(f"home.why.{n}.body"))}</p>'
        + (f'<div class="eg">{html.escape(t("home.why.3.figure", gas=gas, fee=fee))}</div>' if n == 3 else "")
        + "</div>" for n in (1, 2, 3))
    how = "".join(
        f'<div class="br-how-step"><div class="tt">{html.escape(t(f"home.how.{n}.title"))}</div>'
        f'<p>{html.escape(t(f"home.how.{n}.body"))}</p></div>' for n in (1, 2, 3))
    st.markdown(
        f'<div class="br-sect"><div class="br-label">{html.escape(t("home.why.title"))}</div>'
        f'<div class="br-cards">{cards}</div></div>'
        f'<div class="br-sect"><div class="br-label">{html.escape(t("home.how.title"))}</div>'
        f'<div class="br-how">{how}</div></div>',
        unsafe_allow_html=True,
    )
