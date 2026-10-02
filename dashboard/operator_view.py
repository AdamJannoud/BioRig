"""Operator view: the technical panel. Form on the left, live chain state on the right.

This is the dashboard as it stood before the planter flow, kept whole: the protocol terms, the eth_call simulation,
the manual biomass override and the TBA cross-check. scripts/check_dashboard_ui.py and dashboard/test_app_signing.py
read it at ?view=operator.
"""
from __future__ import annotations

import html

import streamlit as st

from dashboard import h3_nullifier
from dashboard.chain import Chain, format_tree_stats, short_hex
from dashboard.strings import t
from dashboard.ui import pill, rows_html


TBA_CHECK_ATTEMPTS = 3


@st.cache_data(ttl=600, show_spinner=False)
def cached_tba_check(_chain: Chain, chain_id: int, proxy: str, token_id: int, block_hint: int):
    """Retried here so a cold render that hits a flaky RPC read still draws the cross-check. st.cache_data does not
    memoise a raised exception (the next call recomputes), so only a success is cached. LookupError is find_mint's
    own verdict after MINT_WALKS confirmed walks and is not retried."""
    for attempt in range(TBA_CHECK_ATTEMPTS):
        try:
            record = _chain.find_mint(token_id)
            return record, _chain.check_tba(token_id, record)
        except LookupError:
            raise
        except Exception:
            if attempt == TBA_CHECK_ATTEMPTS - 1:
                raise


def render(chain: Chain, rpc_chain: int, overview: dict, is_verifier: bool, key_problem: str | None) -> None:
    settings = chain.settings
    explorer = settings.explorer_url
    if key_problem:
        st.warning(t("op.signing_disabled", problem=key_problem))
    signer = chain.signer
    st.markdown(
        f'<div class="br-bar"><span class="br-dot"></span><b>{html.escape(settings.chain_name)}</b>'
        f'<span>chain <span class="mono">{rpc_chain}</span></span>'
        f'<span>proxy <span class="mono">{chain.proxy}</span></span>'
        f'<span>signer <span class="mono">{short_hex(signer, 4, 4) if signer else "none"}</span></span>'
        f'{pill(is_verifier, "VERIFIER_ROLE ✓", "no VERIFIER_ROLE")}'
        f'{pill(not overview["paused"], "live", "paused")}'
        f'<span>block <span class="mono">{overview["block"]:,}</span></span></div>',
        unsafe_allow_html=True,
    )
    st.caption(t("op.proxy_source", source=settings.proxy.source)
               + (t("op.proxy_skipped", skipped="; ".join(settings.proxy.skipped)) if settings.proxy.skipped else ""))

    left, right = st.columns(2, gap="large")

    # ----------------------------------------------------------------------- left: register a tree
    with left:
        st.subheader(t("op.register"))
        planter = st.text_input(t("op.planter"), value=signer or "", help=t("op.planter_help"))
        c1, c2 = st.columns(2)
        dbh = c1.number_input(t("op.dbh"), min_value=0, value=24, step=1)
        biomass = c2.number_input(t("op.biomass"), min_value=0, value=312, step=1)
        c3, c4, c5 = st.columns([1, 1, 0.8])
        lat = c3.number_input(t("op.lat"), min_value=-90.0, max_value=90.0, value=-1.2921, format="%.6f")
        lng = c4.number_input(t("op.lng"), min_value=-180.0, max_value=180.0, value=36.8219, format="%.6f")
        res = c5.number_input(t("op.res"), min_value=0, max_value=15, value=h3_nullifier.DEFAULT_RESOLUTION, step=1)
        salt = st.text_input(t("op.salt"), value="plot-1", help=t("op.salt_help"))

        try:
            d = h3_nullifier.derive(lat, lng, salt, int(res))
        except ValueError as exc:
            st.error(str(exc))
            st.stop()
        h3_nullifier.assert_bytes32(d.nullifier)
        in_use = chain.is_nullifier_active(d.nullifier)
        st.markdown(
            f'<div class="br-label">{html.escape(t("op.nullifier_label"))}</div>'
            f'<div class="br-null">{d.nullifier_hex}</div>'
            f'<div class="br-panel" style="margin-top:8px">'
            + rows_html([
                ("H3 cell", f"{d.cell}  (res {d.resolution}, ≈{d.cell_area_m2:,.0f} m²)"),
                ("preimage", "0x" + d.preimage.hex()),
                ("length", f"{len(d.nullifier)} bytes, non-zero ✓"),
                ("on chain", pill(not in_use, "unused", "already active → NullifierInUse")),
            ]) + "</div>",
            unsafe_allow_html=True,
        )

        st.markdown(f'<div class="br-label">{html.escape(t("op.sim_label"))}</div>', unsafe_allow_html=True)
        sim = None
        if key_problem:
            st.info(t("op.sim_needs_key"))
        elif not signer:
            st.warning(t("op.no_key"))
        else:
            try:
                sim = chain.simulate_mint(planter, d.nullifier, int(dbh), int(biomass))
            except ValueError as exc:
                st.error(t("op.invalid_input", error=exc))
            if sim and sim.ok:
                st.markdown('<div class="br-panel">' + rows_html([
                    ("result", pill(True, "would succeed", "")),
                    ("tokenId", f"#{sim.token_id}"),
                    ("gas estimate", f"{sim.gas:,}"),
                    ("from", sim.sender),
                ]) + "</div>", unsafe_allow_html=True)
            elif sim:
                st.markdown('<div class="br-panel">' + rows_html([
                    ("result", pill(False, "", "would revert")),
                    ("error", html.escape(sim.error or "")),
                    ("from", sim.sender),
                ]) + "</div>", unsafe_allow_html=True)

        if not settings.allow_mint:
            st.info(t("op.read_only"))
        mintable = bool(sim and sim.ok) and settings.allow_mint
        confirm = st.checkbox(t("op.confirm"), disabled=not mintable)
        if st.button(t("op.mint"), type="primary", disabled=not (mintable and confirm)):
            with st.spinner(t("op.minting")):
                try:
                    result = chain.send_mint(planter, d.nullifier, int(dbh), int(biomass), confirmed=confirm)
                except Exception as exc:
                    st.error(t("op.mint_failed", error=exc))
                else:
                    st.session_state["last_mint"] = result
                    st.session_state["token_id"] = result["token_id"]
                    cached_tba_check.clear()
        last = st.session_state.get("last_mint")
        if last:
            st.success(t("op.minted", token=last["token_id"], tx=short_hex(last["tx_hash"]), block=last["block"],
                         gas=last["gas_used"]))
            st.markdown(f'<div class="br-links"><a href="{explorer}/tx/{last["tx_hash"]}" target="_blank">'
                        f'{html.escape(t("op.view_tx"))}</a></div>', unsafe_allow_html=True)

    # ----------------------------------------------------------------------- right: live state
    with right:
        st.session_state.setdefault("token_id", 1)
        token_id = st.number_input(t("op.token_id"), min_value=1, step=1, key="token_id")
        st.subheader(t("op.live_state", token=token_id))
        try:
            stats = chain.get_tree_stats(int(token_id))
        except Exception as exc:
            msg = getattr(exc, "data", None)
            st.warning(t("op.stats_reverted", token=token_id,
                         reason=chain.selectors.get(str(msg)[:10], exc) if msg else exc))
            st.stop()
        active = chain.is_nullifier_active(stats.spatial_nullifier)
        st.markdown('<div class="br-panel">' + rows_html(
            [(k, html.escape(v)) for k, v in format_tree_stats(stats, active)]) + "</div>", unsafe_allow_html=True)

        st.subheader(t("op.tba_title"))
        try:
            record, tba = cached_tba_check(chain, settings.chain_id, chain.proxy, int(token_id), stats.last_updated)
            owner = chain.owner_of(int(token_id))
            uri = chain.token_uri(int(token_id))
        except Exception as exc:
            st.error(t("op.tba_failed", error=exc))
            st.stop()
        bound_ok = tba.bound_token == (settings.chain_id, chain.proxy, int(token_id))
        st.markdown('<div class="br-panel">' + rows_html([
            ("tbaAddress (derived)", tba.derived_offline),
            ("registry.account()", tba.registry_account),
            ("getTreeStats.tbaAddress", tba.stored),
            ("derivations agree", pill(tba.ok, "match ✓", "MISMATCH")),
            ("token()", f"{tba.bound_token[0]} · {short_hex(tba.bound_token[1])} · #{tba.bound_token[2]}"),
            ("bound to this token", pill(bound_ok and tba.supports_6551, "yes · ERC-165 0x6faff5f1", "no")),
            ("salt planter", record.planter),
            ("owner", owner),
            ("mint tx", short_hex(record.tx_hash, 10, 6) + f" · block {record.block_number:,}"),
            ("tokenURI", html.escape(uri) if uri else "(empty: no base URI or generator set)"),
        ]) + "</div>", unsafe_allow_html=True)
        st.caption(t("op.tba_caption"))
        st.markdown(
            '<div class="br-links">'
            f'<a href="{explorer}/address/{chain.proxy}" target="_blank">proxy</a>'
            f'<a href="{explorer}/address/{chain.core_implementation()}" target="_blank">implementation</a>'
            f'<a href="{explorer}/address/{overview["implementation"]}" target="_blank">account impl</a>'
            f'<a href="{explorer}/address/{overview["registry"]}" target="_blank">registry</a>'
            f'<a href="{explorer}/address/{tba.stored}" target="_blank">TBA</a>'
            f'<a href="{explorer}/tx/{record.tx_hash}" target="_blank">tx</a></div>',
            unsafe_allow_html=True,
        )
