from __future__ import annotations

import html
import json
import math

import h3
import streamlit as st
from eth_utils import is_address, to_checksum_address

from dashboard import allometry, h3_nullifier
from dashboard.chain import Chain, compute_tba_address, short_hex, tba_salt
from dashboard.geolocate import geolocate
from dashboard.strings import t
from dashboard.ui import rwos_html

PILOT = dict(lat=-1.2921, lng=36.8219)
DEFAULT_REFERENCE = "plot-1"
DEFAULT_DBH = 24
SIZES = {"small": 12, "medium": 11, "large": 10}

DEMO_REFERENCES = tuple(f"plot-{n}" for n in range(1, 9))

def default_reference(is_active, references: tuple[str, ...] = DEMO_REFERENCES) -> str:
    try:
        for ref in references:
            if not is_active(h3_nullifier.derive(PILOT["lat"], PILOT["lng"], ref, SIZES["small"]).nullifier):
                return ref
    except Exception:
        pass
    return DEFAULT_REFERENCE

def _defaults(chain: Chain, reference: str | None = None) -> dict:
    return {"p_step": 1, "p_dbh": DEFAULT_DBH, "p_lat": PILOT["lat"], "p_lng": PILOT["lng"], "p_from": "default",
            "p_size": "small", "p_ref": default_reference(chain.is_nullifier_active) if reference is None else reference,
            "p_wallet": chain.signer or "", "p_gps_ts": None, "p_check": None, "p_last_mint": None}

def _carry(chain: Chain) -> None:
    ss = st.session_state
    for k, v in _defaults(chain, ss["p_ref"] if "p_ref" in ss else None).items():
        ss[k] = ss[k] if k in ss else v

def _go(step: int) -> None:
    st.session_state["p_step"] = step

def _start_over(chain: Chain) -> None:
    for k, v in _defaults(chain).items():
        st.session_state[k] = v

def _typed() -> None:
    st.session_state["p_from"] = "typed"

def steps_html(current: int) -> str:
    out = []
    for n in (1, 2, 3):
        cls = "on" if n == current else ("done" if n < current else "")
        out.append(f'<span class="br-step {cls}"><span class="n">{"✓" if n < current else n}</span>'
                   f'<span class="long">{html.escape(t(f"step.{n}"))}</span>'
                   f'<span class="short">{html.escape(t(f"step.{n}.short"))}</span></span>')
    return '<div class="br-steps" aria-label="steps">' + "".join(out) + "</div>"

def metrics_html(e: allometry.Estimate) -> str:
    tiles = [("measure.biomass", e.biomass_kg, "kg"), ("measure.carbon", e.carbon_kg, "kg"),
             ("measure.co2e", e.co2e_kg, "kg CO₂e")]
    return '<div class="br-metrics">' + "".join(
        f'<div class="br-metric"><div class="lab">{html.escape(t(k))}</div>'
        f'<div class="num">{v:,.0f} <small>{u}</small></div></div>' for k, v, u in tiles) + "</div>"

def status_html(kind: str, icon: str, markdown_text: str) -> str:
    body = html.escape(markdown_text)
    parts = body.split("**")
    body = "".join(f"<b>{p}</b>" if i % 2 else p for i, p in enumerate(parts))
    return f'<div class="br-status {kind}"><span class="ic">{icon}</span><span>{body}</span></div>'

def across_m(area_m2: float) -> float:
    edge = math.sqrt(2 * area_m2 / (3 * math.sqrt(3)))
    return math.sqrt(3) * edge

def plot_svg(lat: float, lng: float, resolution: int) -> str:
    cell = h3.latlng_to_cell(lat, lng, resolution)
    k = math.cos(math.radians(lat))

    def local(la, ln):
        return (ln - lng) * 111_320 * k, -(la - lat) * 110_540

    main = [local(*p) for p in h3.cell_to_boundary(cell)]
    cx = sum(x for x, _ in main) / 6
    cy = sum(y for _, y in main) / 6
    s = 54 / max(math.hypot(x - cx, y - cy) for x, y in main)

    def pts(boundary):
        return " ".join(f"{150 + (x - cx) * s:.1f},{90 + (y - cy) * s:.1f}" for x, y in boundary)

    faint = "".join(
        f'<polygon points="{pts([local(*p) for p in h3.cell_to_boundary(c)])}" '
        'style="fill:none;stroke:var(--app-plot-faint);stroke-width:1.5"/>'
        for c in h3.grid_disk(cell, 1) if c != cell)
    tx, ty = 150 + (0 - cx) * s, 90 + (0 - cy) * s
    area = h3.average_hexagon_area(resolution, unit="m^2")
    return (f'<div class="br-plot"><svg viewBox="0 0 300 190" role="img" aria-label="{html.escape(t("locate.map_alt"))}">'
            f'{faint}<polygon points="{pts(main)}" style="fill:var(--app-plot-cell);stroke:var(--app-plot-line);'
            f'stroke-width:2.5"/>'
            f'<circle cx="{tx:.1f}" cy="{ty:.1f}" r="6" style="fill:var(--app-forest);stroke:var(--app-gold);'
            f'stroke-width:3"/>'
            f'<text x="150" y="176" text-anchor="middle" style="font:12px var(--app-font);fill:var(--app-muted)">'
            f'{html.escape(t("locate.map_caption", area=area))}</text></svg></div>')

def plain_reason(error: str | None) -> str:
    name = (error or "").split("(", 1)[0].strip()
    key = f"claim.reason.{name}"
    try:
        return t(key)
    except KeyError:
        return t("claim.reason.other")

@st.cache_data(ttl=60, show_spinner=False)
def live_trees(_chain: Chain, chain_id: int, proxy: str, limit: int = 24) -> list[tuple[int, int, int, bool]]:
    out = []
    for token_id in range(1, limit + 1):
        try:
            s = _chain.get_tree_stats(token_id)
        except Exception:
            break
        out.append((token_id, s.dbh, s.biomass, s.is_alive))
    return out

def _measure() -> None:
    st.markdown(f'<div class="br-h">{html.escape(t("measure.title"))}</div>'
                f'<p class="br-lede">{html.escape(t("measure.lede"))}</p>', unsafe_allow_html=True)
    dbh = st.slider(t("measure.slider"), allometry.DBH_MIN_CM, allometry.DBH_MAX_CM, format="%d cm", key="p_dbh")
    e = allometry.estimate(int(dbh))
    st.markdown(metrics_html(e) + f'<p class="br-note">'
                f'{html.escape(t("measure.assumes", height=e.height_m, density=allometry.DEFAULT_WOOD_DENSITY))}</p>',
                unsafe_allow_html=True)
    st.caption(t("measure.note"))
    st.button(t("nav.continue"), type="primary", key="p_next1", on_click=_go, args=(2,))

def _derive():
    ss = st.session_state
    salt = (ss["p_ref"] or "").strip() or DEFAULT_REFERENCE
    return h3_nullifier.derive(float(ss["p_lat"]), float(ss["p_lng"]), salt, SIZES.get(ss["p_size"] or "small", 12))

def _locate(chain: Chain) -> None:
    ss = st.session_state
    st.markdown(f'<div class="br-h">{html.escape(t("locate.title"))}</div>'
                f'<p class="br-lede">{html.escape(t("locate.lede"))}</p>', unsafe_allow_html=True)
    reading = geolocate(label=t("locate.gps_button"), waiting=t("locate.gps_waiting"), found=t("locate.gps_found"),
                        denied=t("locate.gps_denied"), unavailable=t("locate.gps_unavailable"),
                        unsupported=t("locate.gps_unsupported"), key="p_geo")
    if reading and reading.get("ts") != ss["p_gps_ts"]:
        ss["p_gps_ts"] = reading.get("ts")
        if "lat" in reading and "lng" in reading:
            ss["p_lat"], ss["p_lng"] = round(float(reading["lat"]), 6), round(float(reading["lng"]), 6)
            ss["p_from"] = "gps"
    st.caption(t("locate.permission_note"))
    with st.expander(t("locate.type_instead"), expanded=ss["p_from"] == "typed"):
        c1, c2 = st.columns(2)
        c1.number_input(t("locate.lat"), min_value=-90.0, max_value=90.0, format="%.6f", key="p_lat", on_change=_typed)
        c2.number_input(t("locate.lng"), min_value=-180.0, max_value=180.0, format="%.6f", key="p_lng",
                        on_change=_typed)
        st.text_input(t("locate.reference"), key="p_ref", placeholder=t("locate.reference_placeholder"),
                      help=t("locate.reference_help", default=DEFAULT_REFERENCE))
    st.segmented_control(t("locate.size"), list(SIZES), key="p_size",
                         format_func=lambda s: t(f"locate.size.{s}"))

    try:
        d = _derive()
    except ValueError as exc:
        st.error(t("locate.bad_coords", error=exc))
        return
    taken = chain.is_nullifier_active(d.nullifier)
    size = ss["p_size"] or "small"
    left, right = st.columns([1, 1], gap="medium")
    left.markdown(plot_svg(d.lat, d.lng, d.resolution), unsafe_allow_html=True)
    right.markdown(
        '<div class="br-panel" style="margin-top:0">' + rows_html([
            (t("locate.coords"), f'<span class="mono">{d.lat:.6f}, {d.lng:.6f}</span>'),
            (t("locate.from"), html.escape(t(f"locate.from.{ss['p_from']}"))),
            (t("locate.size"), html.escape(t("locate.size_value", size=t(f"locate.size.{size}"),
                                             across=across_m(d.cell_area_m2)))),
            (t("locate.plot_id"), f'<span class="mono">{short_hex(d.nullifier_hex, 6, 4)}</span>'),
        ], plain=True) + "</div>"
        + (status_html("warn", "!", t("locate.taken")) if taken else status_html("", "✓", t("locate.free"))),
        unsafe_allow_html=True,
    )
    st.caption(t("locate.note"))
    with st.container(horizontal=True, gap="small"):
        st.button(t("nav.continue"), type="primary", key="p_next2", on_click=_go, args=(3,))
        st.button(t("nav.back"), key="p_back2", on_click=_go, args=(1,))

def _fee_celo(chain: Chain, gas: int) -> str | None:
    try:
        wei = gas * chain.gas_price_wei()
    except Exception:
        return None
    return f"{wei / 10**18:.3g}"

def _claim(chain: Chain, overview: dict, key_problem: str | None) -> None:
    ss = st.session_state
    settings = chain.settings
    signer = None if key_problem else chain.signer
    st.markdown(f'<div class="br-h">{html.escape(t("claim.title"))}</div>'
                f'<p class="br-lede">{html.escape(t("claim.lede"))}</p>', unsafe_allow_html=True)
    st.text_input(t("claim.wallet"), key="p_wallet", help=t("claim.wallet_help"))
    e = allometry.estimate(int(ss["p_dbh"]))
    try:
        d = _derive()
    except ValueError as exc:
        st.error(t("locate.bad_coords", error=exc))
        return
    taken = chain.is_nullifier_active(d.nullifier)
    wallet = (ss["p_wallet"] or "").strip()
    inputs = (wallet, d.nullifier_hex, e.dbh_cm, e.mint_biomass_kg)
    check = ss["p_check"] if ss["p_check"] and ss["p_check"]["inputs"] == inputs else None
    sim = check["sim"] if check else None

    tree_wallet = t("claim.wallet_tree_pending")
    if sim and sim.ok and is_address(wallet):
        tree_wallet = compute_tba_address(overview["registry"], overview["implementation"],
                                          tba_salt(sim.token_id, to_checksum_address(wallet), d.nullifier),
                                          settings.chain_id, chain.proxy, sim.token_id)
    st.markdown('<div class="br-panel">' + rows_html([
        (t("claim.registered_to"),
         f'<span class="mono">{html.escape(short_hex(wallet, 6, 4) if is_address(wallet) else wallet or "—")}</span>'),
        (t("claim.dbh"), html.escape(t("claim.dbh_value", dbh=e.dbh_cm))),
        (t("claim.biomass"), html.escape(t("claim.biomass_value", kg=e.mint_biomass_kg))),
        (t("claim.plot"), html.escape(f"{d.lat:.6f}, {d.lng:.6f} · "
                                      + t("claim.plot_taken" if taken else "claim.plot_free"))),
        (t("claim.wallet_tree"), f'<span class="mono">{html.escape(short_hex(tree_wallet, 6, 5))}</span>'
         if tree_wallet.startswith("0x") else html.escape(tree_wallet)),
    ], plain=True) + "</div>", unsafe_allow_html=True)

    with st.container(horizontal=True, gap="small"):
        run = st.button(t("claim.check"), type="primary", key="p_check_btn", disabled=not signer)
        st.button(t("nav.back"), key="p_back3", on_click=_go, args=(2,))
        st.button(t("nav.start_over"), key="p_reset", on_click=_start_over, args=(chain,))

    if not signer:
        st.markdown(status_html("warn", "!", t("claim.no_account")), unsafe_allow_html=True)
        return
    if run:
        with st.spinner(t("claim.checking")):
            if not is_address(wallet):
                result, fee = None, None
            else:
                result = chain.simulate_mint(wallet, d.nullifier, e.dbh_cm, e.mint_biomass_kg)
                fee = _fee_celo(chain, result.gas) if result.ok else None
        ss["p_check"] = {"inputs": inputs, "sim": result, "fee": fee, "bad_wallet": not is_address(wallet)}
        st.rerun()

    if not check:
        st.markdown(status_html("idle", "◐", t("claim.idle")), unsafe_allow_html=True)
    elif check["bad_wallet"]:
        st.markdown(status_html("warn", "!", t("claim.not_this_one", reason=t("claim.reason.wallet"))),
                    unsafe_allow_html=True)
    elif sim.ok:
        ready = (t("claim.ready", token=sim.token_id, fee=check["fee"]) if check["fee"]
                 else t("claim.ready_nofee", token=sim.token_id))
        st.markdown(status_html("", "✓", ready), unsafe_allow_html=True)
        if settings.allow_mint:
            _register(chain, wallet, d, e)
        else:
            st.markdown(status_html("idle", "■", t("claim.demo_readonly")), unsafe_allow_html=True)
    else:
        st.markdown(status_html("warn", "!", t("claim.not_this_one", reason=plain_reason(sim.error))),
                    unsafe_allow_html=True)

    last = ss["p_last_mint"]
    if last:
        url = f"{settings.explorer_url}/tx/{last['tx_hash']}"
        st.markdown(status_html("", "✓", t("claim.registered", token=last["token_id"]))
                    + f'<p class="br-note"><a class="br-link" href="{url}" target="_blank">'
                      f'{html.escape(t("claim.explorer"))}</a></p>', unsafe_allow_html=True)
        st.download_button(t("claim.download"), json.dumps(last, indent=2), file_name=f"biorig-tree-{last['token_id']}.json",
                           mime="application/json", key="p_download")
    st.caption(t("claim.note"))

def _register(chain: Chain, wallet: str, d, e: allometry.Estimate) -> None:
    confirm = st.checkbox(t("claim.confirm"), key="p_confirm")
    if st.button(t("claim.register"), type="primary", key="p_register", disabled=not confirm):
        with st.spinner(t("claim.registering")):
            try:
                result = chain.send_mint(wallet, d.nullifier, e.dbh_cm, e.mint_biomass_kg, confirmed=confirm)
            except Exception as exc:
                st.error(t("claim.register_failed", error=exc))
                return
        st.session_state["p_last_mint"] = {**result, "chain_id": chain.settings.chain_id, "contract": chain.proxy,
                                           "planter": wallet, "trunk_diameter_cm": e.dbh_cm,
                                           "stored_biomass_kg": e.mint_biomass_kg, "plot_id": d.nullifier_hex,
                                           "h3_cell": d.cell, "lat": d.lat, "lng": d.lng}
        st.session_state["p_check"] = None
        live_trees.clear()
        st.rerun()

def _trees(chain: Chain) -> None:
    settings = chain.settings
    trees = live_trees(chain, settings.chain_id, chain.proxy)
    st.markdown(f'<div class="br-label" style="margin-top:22px">{html.escape(t("trees.title"))}</div>',
                unsafe_allow_html=True)
    if not trees:
        st.caption(t("trees.none"))
        return
    badges = "".join(
        f'<span class="br-tree"><b>{html.escape(t("trees.badge", token=i))}</b>'
        f'<span class="br-pill {"br-ok" if alive else "br-bad"}">{t("trees.alive" if alive else "trees.dead")}</span>'
        f'<span class="facts">{html.escape(t("trees.facts", dbh=dbh, kg=kg))}</span>'
        f'<a href="{settings.explorer_url}/token/{chain.proxy}/instance/{i}" target="_blank">'
        f'{html.escape(t("trees.explorer"))}</a></span>' for i, dbh, kg, alive in trees)
    st.markdown(f'<div class="br-trees">{badges}</div><p class="br-note">{html.escape(t("trees.lede"))} '
                f'<a class="br-link" href="{settings.explorer_url}/address/{chain.proxy}" target="_blank">'
                f'{html.escape(t("trees.contract"))}</a></p>', unsafe_allow_html=True)

def render(chain: Chain, overview: dict, key_problem: str | None) -> None:
    _carry(chain)
    step = st.session_state["p_step"]
    st.markdown(steps_html(step), unsafe_allow_html=True)
    with st.container(key="br-card"):
        if step == 1:
            _measure()
        elif step == 2:
            _locate(chain)
        else:
            _claim(chain, overview, key_problem)
    _trees(chain)
