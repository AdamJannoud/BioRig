"""BioRig demo dashboard. Form on the left, live chain state on the right.

    .venv/bin/streamlit run dashboard/app.py

The verifier key is read from .env on the server and never sent to the browser: every signature happens
in this Python process.
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard import h3_nullifier  # noqa: E402
from dashboard.chain import Chain, format_tree_stats, short_hex  # noqa: E402
from dashboard.config import ChainSelectionError, ProxyResolutionError, load_settings  # noqa: E402

st.set_page_config(page_title="BioRig demo", page_icon="🌳", layout="wide")

# --------------------------------------------------------------------------- theme tokens
# Colours come only from --app-* custom properties, keyed on <html data-app-mode>. The small script below
# sets data-app-mode from the background Streamlit actually painted, so the panels follow Streamlit's own
# light/dark setting instead of a separate prefers-color-scheme query.
st.markdown("""
<style>
html, html[data-app-mode="light"] {
  --app-bg: #f6f3ec; --app-surface: #fbf9f4; --app-field: #f1ede3; --app-rule: #d9d3c5;
  --app-text: #1d1b17; --app-muted: #6b6558; --app-accent: #2456d6; --app-accent-text: #ffffff;
  --app-ok: #1f7a3d; --app-ok-bg: #e3f1e6; --app-bad: #b42318; --app-bad-bg: #fbe7e5;
  --app-font: "IBM Plex Sans", -apple-system, "Segoe UI", Roboto, sans-serif;
  --app-mono: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  --app-radius: 6px; --app-shadow: none;
}
html[data-app-mode="dark"] {
  --app-bg: #0e1116; --app-surface: #171b22; --app-field: #0e1116; --app-rule: #262c36;
  --app-text: #e6e9ef; --app-muted: #8b95a3; --app-accent: #2f6df6; --app-accent-text: #ffffff;
  --app-ok: #4ade80; --app-ok-bg: #10331f; --app-bad: #f87171; --app-bad-bg: #3a1414;
}
.br-bar { display:flex; flex-wrap:wrap; align-items:center; gap:6px 14px; padding:9px 14px;
  background:var(--app-surface); border:1px solid var(--app-rule); border-radius:var(--app-radius);
  font:12px/1.5 var(--app-font); color:var(--app-muted); margin-bottom:6px; }
.br-bar b { color:var(--app-text); font-weight:600; }
.br-bar .mono { font-family:var(--app-mono); color:var(--app-text); }
.br-dot { width:9px; height:9px; border-radius:50%; background:var(--app-ok); display:inline-block; }
.br-panel { background:var(--app-surface); border:1px solid var(--app-rule); border-radius:var(--app-radius);
  padding:12px 14px; margin:4px 0 12px; box-shadow:var(--app-shadow); }
.br-label { font:600 11px/1.4 var(--app-font); text-transform:uppercase; letter-spacing:.06em;
  color:var(--app-muted); margin-bottom:6px; }
.br-row { display:flex; justify-content:space-between; gap:12px; padding:4px 0;
  border-bottom:1px solid var(--app-rule); font-size:13px; }
.br-row:last-child { border-bottom:0; }
.br-k { color:var(--app-muted); font-family:var(--app-font); white-space:nowrap; }
.br-v { color:var(--app-text); font-family:var(--app-mono); font-size:12px; font-variant-numeric:tabular-nums;
  text-align:right; overflow-wrap:anywhere; }
.br-pill { font:600 10.5px/1 var(--app-font); padding:3px 8px; border-radius:99px; display:inline-block; }
.br-ok { background:var(--app-ok-bg); color:var(--app-ok); }
.br-bad { background:var(--app-bad-bg); color:var(--app-bad); }
.br-links a { color:var(--app-accent); margin-right:12px; font-size:13px; }
.br-null { font-family:var(--app-mono); font-size:12px; color:var(--app-text); background:var(--app-field);
  border:1px solid var(--app-rule); border-radius:var(--app-radius); padding:6px 8px; overflow-wrap:anywhere; }
</style>
""", unsafe_allow_html=True)

components.html("""
<script>
(function () {
  const doc = window.parent.document;
  function mode() {
    const app = doc.querySelector('.stApp') || doc.body;
    const m = getComputedStyle(app).backgroundColor.match(/\\d+(\\.\\d+)?/g);
    if (!m) return;
    const lum = (0.299 * m[0] + 0.587 * m[1] + 0.114 * m[2]) / 255;
    const want = lum < 0.5 ? 'dark' : 'light';
    if (doc.documentElement.getAttribute('data-app-mode') !== want) doc.documentElement.setAttribute('data-app-mode', want);
  }
  mode();
  new MutationObserver(mode).observe(doc.body, {attributes: true, subtree: true, attributeFilter: ['class', 'style']});
})();
</script>
""", height=0)


def rows_html(rows: list[tuple[str, str]]) -> str:
    return "".join(f'<div class="br-row"><span class="br-k">{html.escape(k)}</span>'
                   f'<span class="br-v">{v}</span></div>' for k, v in rows)


def pill(ok: bool, yes: str, no: str) -> str:
    return f'<span class="br-pill {"br-ok" if ok else "br-bad"}">{html.escape(yes if ok else no)}</span>'


# --------------------------------------------------------------------------- connection

@st.cache_resource(show_spinner="Connecting to the chain…")
def get_chain() -> Chain:
    return Chain(load_settings())


@st.cache_data(ttl=600, show_spinner=False)
def cached_tba_check(token_id: int, block_hint: int):
    chain = get_chain()
    record = chain.find_mint(token_id)
    return record, chain.check_tba(token_id, record)


try:
    chain = get_chain()
    settings = chain.settings
    rpc_chain = chain.assert_chain()
    overview = chain.overview()
    is_verifier = chain.signer_is_verifier()
except (ChainSelectionError, ProxyResolutionError) as exc:
    st.error(str(exc))
    st.stop()
except Exception as exc:  # RPC down, wrong chain: show it rather than a blank page
    st.error(f"Could not reach the chain: {exc}")
    st.stop()

explorer = settings.explorer_url
st.set_page_config(page_title=f"BioRig · {settings.chain_name} demo")
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
st.caption(f"Proxy resolved from `{settings.proxy.source}`"
           + (f" (skipped: {'; '.join(settings.proxy.skipped)})" if settings.proxy.skipped else ""))
st.caption("BioRig — project lead, author and sole deployer: Adam Jannoud")

left, right = st.columns(2, gap="large")

# --------------------------------------------------------------------------- left: register a tree
with left:
    st.subheader("Register a tree")
    planter = st.text_input("planter", value=signer or "",
                            help="Wallet that receives the tree NFT. Defaults to the verifier account; paste a "
                                 "smallholder wallet to mint to them.")
    c1, c2 = st.columns(2)
    dbh = c1.number_input("initialDBH (cm, uint96)", min_value=0, value=24, step=1)
    biomass = c2.number_input("initialBiomass (kg, uint96)", min_value=0, value=312, step=1)
    c3, c4, c5 = st.columns([1, 1, 0.8])
    lat = c3.number_input("lat", min_value=-90.0, max_value=90.0, value=-1.2921, format="%.6f")
    lng = c4.number_input("lng", min_value=-180.0, max_value=180.0, value=36.8219, format="%.6f")
    res = c5.number_input("H3 res", min_value=0, max_value=15, value=h3_nullifier.DEFAULT_RESOLUTION, step=1)
    salt = st.text_input("salt", value="plot-1",
                         help="Same cell + same salt = same nullifier, which the contract refuses twice "
                              "(NullifierInUse). A new salt registers another tree in the same plot.")

    try:
        d = h3_nullifier.derive(lat, lng, salt, int(res))
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
    h3_nullifier.assert_bytes32(d.nullifier)
    in_use = chain.is_nullifier_active(d.nullifier)
    st.markdown(
        f'<div class="br-label">spatialNullifier (auto) · keccak256(uint64(h3Cell) ++ salt)</div>'
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

    st.markdown('<div class="br-label">eth_call simulation (runs on every change, never broadcasts)</div>',
                unsafe_allow_html=True)
    sim = None
    if not signer:
        st.warning("PRIVATE_KEY is not set in .env, so the verifier account is unavailable.")
    else:
        try:
            sim = chain.simulate_mint(planter, d.nullifier, int(dbh), int(biomass))
        except ValueError as exc:
            st.error(f"Invalid input: {exc}")
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
        st.info("Read-only deployment: the form and the eth_call simulation run, the broadcast does not. "
                "Set ALLOW_MINT=true in Secrets to enable signing a real mintTree.")
    mintable = bool(sim and sim.ok) and settings.allow_mint
    confirm = st.checkbox("I confirm: broadcast this mintTree from the server-side verifier key",
                          disabled=not mintable)
    if st.button("Mint tree", type="primary", disabled=not (mintable and confirm)):
        with st.spinner("Signing on the server and waiting for the receipt…"):
            try:
                result = chain.send_mint(planter, d.nullifier, int(dbh), int(biomass), confirmed=confirm)
            except Exception as exc:
                st.error(f"Mint failed: {exc}")
            else:
                st.session_state["last_mint"] = result
                st.session_state["token_id"] = result["token_id"]
                cached_tba_check.clear()
    last = st.session_state.get("last_mint")
    if last:
        st.success(f"✔ minted token #{last['token_id']} · tx {short_hex(last['tx_hash'])} · "
                   f"block {last['block']:,} · gas {last['gas_used']:,}")
        st.markdown(f'<div class="br-links"><a href="{explorer}/tx/{last["tx_hash"]}" target="_blank">'
                    f'view tx on Blockscout</a></div>', unsafe_allow_html=True)

# --------------------------------------------------------------------------- right: live state
with right:
    st.session_state.setdefault("token_id", 1)
    token_id = st.number_input("tokenId", min_value=1, step=1, key="token_id")
    st.subheader(f"Live state · getTreeStats({token_id})")
    try:
        stats = chain.get_tree_stats(int(token_id))
    except Exception as exc:
        msg = getattr(exc, "data", None)
        st.warning(f"getTreeStats({token_id}) reverted: "
                   f"{chain.selectors.get(str(msg)[:10], exc) if msg else exc}. No tree with this id yet.")
        st.stop()
    active = chain.is_nullifier_active(stats.spatial_nullifier)
    st.markdown('<div class="br-panel">' + rows_html(
        [(k, html.escape(v)) for k, v in format_tree_stats(stats, active)]) + "</div>", unsafe_allow_html=True)

    st.subheader("ERC-6551 token bound account")
    try:
        record, tba = cached_tba_check(int(token_id), stats.last_updated)
        owner = chain.owner_of(int(token_id))
        uri = chain.token_uri(int(token_id))
    except Exception as exc:
        st.error(f"TBA derivation failed: {exc}")
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
    st.caption("Derived as CREATE2(registry, salt = keccak256(tokenId ++ planter ++ spatialNullifier), "
               "ERC-1167(implementation) ++ abi.encode(salt, chainId, proxy, tokenId)), exactly as mintTree "
               "calls createAccount; the planter comes from the mint's Transfer log.")
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
