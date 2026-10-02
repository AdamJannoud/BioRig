"""Shared look for both views: the brand tokens, light/dark mode, the header, and small HTML helpers.

Colours come only from --app-* custom properties, keyed on <html data-app-mode>. A small script sets data-app-mode
from the background Streamlit actually painted, so the page follows Streamlit's own light/dark setting instead of a
separate prefers-color-scheme query. Palette: Celo gold and forest (assets/brand/README.md).
"""
from __future__ import annotations

import html
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from dashboard.strings import t

BRAND_DIR = Path(__file__).resolve().parent / "brand"
FAVICON = BRAND_DIR / "favicon.png"

CSS = """
<style>
html, html[data-app-mode="light"] {
  --app-bg: #F7F5EE; --app-surface: #FFFFFF; --app-field: #FBF9F2; --app-rule: #E3E0D3;
  --app-text: #0F1D17; --app-muted: #5B6B62; --app-accent: #0A5B3A; --app-accent-text: #FFFFFF;
  --app-gold: #FCFF52; --app-gold-deep: #E8EC2A; --app-gold-ink: #1A1C00; --app-gold-ring: rgba(252,255,82,.45);
  --app-forest: #023A24; --app-wordmark: #023A24;
  --app-chip-bg: #EAF3EC; --app-chip-text: #0A5B3A; --app-step-n: #EDEAE0;
  --app-ok: #1F7A3D; --app-ok-bg: #EAF3EC; --app-ok-rule: #CDE3D3;
  --app-warn: #8A6D00; --app-warn-bg: #FBF6E4; --app-warn-rule: #EADFB4;
  --app-bad: #B42318; --app-bad-bg: #FBE7E5;
  --app-plot-a: #E8EFE6; --app-plot-b: #DCE7DA; --app-plot-grid: rgba(2,58,36,.07);
  --app-plot-cell: rgba(232,236,42,.38); --app-plot-line: #023A24; --app-plot-faint: rgba(2,58,36,.18);
  --app-font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
  --app-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  --app-radius: 14px; --app-radius-sm: 11px; --app-shadow: 0 1px 3px rgba(2,58,36,.06);
}
html[data-app-mode="dark"] {
  --app-bg: #06170F; --app-surface: #0D2318; --app-field: #0A1E14; --app-rule: #1E3A2B;
  --app-text: #E9F1EA; --app-muted: #9FB5A6; --app-accent: #8FE0AC; --app-accent-text: #06170F;
  --app-gold-ring: rgba(252,255,82,.28); --app-wordmark: #E9F1EA;
  --app-chip-bg: #12331F; --app-chip-text: #8FE0AC; --app-step-n: #173527;
  --app-ok: #8FE0AC; --app-ok-bg: #0F2A1B; --app-ok-rule: #1E3A2B;
  --app-warn: #E8C547; --app-warn-bg: #2A2410; --app-warn-rule: #4A3F18;
  --app-bad: #F87171; --app-bad-bg: #3A1414;
  --app-plot-a: #0C2418; --app-plot-b: #0A1E14; --app-plot-grid: rgba(233,241,234,.06);
  --app-plot-cell: rgba(252,255,82,.22); --app-plot-line: #FCFF52; --app-plot-faint: rgba(233,241,234,.16);
  --app-shadow: none;
}
.block-container { padding-top: 4.25rem; max-width: 1240px; }

/* ---- header */
.br-appbar { display:flex; align-items:center; gap:10px 14px; flex-wrap:wrap; min-height:48px;
  background:var(--app-surface); border:1px solid var(--app-rule); border-radius:12px; padding:9px 16px;
  box-shadow:var(--app-shadow); }
.br-appbar svg { flex:none; }
.br-wordmark { font:700 19px/1 var(--app-font); letter-spacing:-.03em; color:var(--app-wordmark); }
.br-wordmark .dot { color:var(--app-gold-deep); }
html[data-app-mode="dark"] .br-mark-light, html:not([data-app-mode="dark"]) .br-mark-dark { display:none; }
.br-chip { font:600 11.5px/1 var(--app-font); padding:5px 9px; border-radius:99px; background:var(--app-chip-bg);
  color:var(--app-chip-text); display:inline-flex; align-items:center; gap:6px; white-space:nowrap; }
.br-chip .d { width:7px; height:7px; border-radius:50%; background:var(--app-ok); }
.br-chip.paused .d { background:var(--app-warn); }
.st-key-br-view [data-testid="stWidgetLabel"] { display:none; }
.st-key-br-view { display:flex; justify-content:flex-end; }

/* ---- operator view panels (unchanged structure, brand palette) */
.br-bar { display:flex; flex-wrap:wrap; align-items:center; gap:6px 14px; padding:9px 14px;
  background:var(--app-surface); border:1px solid var(--app-rule); border-radius:var(--app-radius-sm);
  font:12px/1.5 var(--app-font); color:var(--app-muted); margin-bottom:6px; }
.br-bar b { color:var(--app-text); font-weight:600; }
.br-bar .mono { font-family:var(--app-mono); color:var(--app-text); overflow-wrap:anywhere; }
.br-dot { width:9px; height:9px; border-radius:50%; background:var(--app-ok); display:inline-block; }
.br-panel { background:var(--app-surface); border:1px solid var(--app-rule); border-radius:var(--app-radius-sm);
  padding:12px 14px; margin:4px 0 12px; box-shadow:var(--app-shadow); }
.br-label { font:600 11px/1.4 var(--app-font); text-transform:uppercase; letter-spacing:.06em;
  color:var(--app-muted); margin-bottom:6px; }
.br-row { display:flex; justify-content:space-between; gap:12px; padding:6px 0;
  border-bottom:1px solid var(--app-rule); font-size:13px; }
.br-row:last-child { border-bottom:0; }
.br-k { color:var(--app-muted); font-family:var(--app-font); white-space:nowrap; }
.br-v { color:var(--app-text); font-family:var(--app-mono); font-size:12px; font-variant-numeric:tabular-nums;
  text-align:right; overflow-wrap:anywhere; min-width:0; }
.br-v.plain { font-family:var(--app-font); font-size:13px; font-weight:600; }
.br-v .mono { font-family:var(--app-mono); font-size:12.5px; font-weight:500; }
.br-pill { font:600 10.5px/1 var(--app-font); padding:3px 8px; border-radius:99px; display:inline-block; }
.br-ok { background:var(--app-ok-bg); color:var(--app-ok); }
.br-bad { background:var(--app-bad-bg); color:var(--app-bad); }
.br-links a, a.br-link, .br-tree a { color:var(--app-accent) !important; margin-right:12px; font-size:13px; }
.br-null { font-family:var(--app-mono); font-size:12px; color:var(--app-text); background:var(--app-field);
  border:1px solid var(--app-rule); border-radius:var(--app-radius-sm); padding:6px 8px; overflow-wrap:anywhere; }

/* ---- planter wizard */
.br-steps { display:flex; gap:8px; align-items:center; margin:6px 0 4px; flex-wrap:wrap; }
.br-step { display:flex; align-items:center; gap:8px; font:500 12.5px/1.2 var(--app-font); color:var(--app-muted);
  background:var(--app-surface); border:1px solid var(--app-rule); border-radius:99px; padding:6px 12px; }
.br-step .n { width:18px; height:18px; border-radius:50%; background:var(--app-step-n); color:var(--app-muted);
  font:700 11px/18px var(--app-font); text-align:center; flex:none; }
.br-step.on { color:var(--app-text); border-color:var(--app-gold-deep); box-shadow:0 0 0 3px var(--app-gold-ring); }
.br-step.on .n, .br-step.done .n { background:var(--app-gold); color:var(--app-gold-ink); }
.br-step .short { display:none; }
.st-key-br-card { background:var(--app-surface); border:1px solid var(--app-rule) !important;
  border-radius:var(--app-radius) !important; padding:18px 20px; box-shadow:var(--app-shadow); }
.br-h { font:700 19px/1.25 var(--app-font); letter-spacing:-.01em; color:var(--app-text); margin:0 0 2px; }
.br-lede { color:var(--app-muted); font-size:14px; margin:0 0 4px; }
.br-note { color:var(--app-muted); font-size:13px; margin:6px 0 0; }
.br-metrics { display:flex; gap:12px; flex-wrap:wrap; margin:4px 0 2px; }
.br-metric { flex:1; min-width:112px; background:var(--app-field); border:1px solid var(--app-rule);
  border-radius:var(--app-radius-sm); padding:10px 12px; }
.br-metric .lab { font:600 10.5px/1.3 var(--app-font); text-transform:uppercase; letter-spacing:.06em;
  color:var(--app-muted); }
.br-metric .num { font:700 22px/1.3 var(--app-font); letter-spacing:-.02em; color:var(--app-text);
  font-variant-numeric:tabular-nums; }
.br-metric .num small { font-weight:600; font-size:12px; color:var(--app-muted); }
.br-status { display:flex; gap:10px; align-items:flex-start; background:var(--app-ok-bg);
  border:1px solid var(--app-ok-rule); border-radius:var(--app-radius-sm); padding:12px 14px; font-size:13.5px;
  color:var(--app-text); margin:8px 0 4px; }
.br-status .ic { font-weight:700; color:var(--app-ok); flex:none; }
.br-status.warn { background:var(--app-warn-bg); border-color:var(--app-warn-rule); }
.br-status.warn .ic { color:var(--app-warn); }
.br-status.idle { background:var(--app-field); border-color:var(--app-rule); color:var(--app-muted); }
.br-status.idle .ic { color:var(--app-muted); }
.br-status a { color:var(--app-accent); }
.br-plot { position:relative; border-radius:12px; border:1px solid var(--app-rule); overflow:hidden;
  background-image:linear-gradient(var(--app-plot-grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--app-plot-grid) 1px, transparent 1px),
    linear-gradient(160deg, var(--app-plot-a), var(--app-plot-b) 55%, var(--app-plot-a));
  background-size:26px 26px, 26px 26px, auto; }
.br-plot svg { display:block; width:100%; height:auto; }
.br-trees { display:flex; gap:10px; flex-wrap:wrap; }
.br-tree { display:flex; align-items:center; gap:10px; background:var(--app-surface); border:1px solid var(--app-rule);
  border-radius:var(--app-radius-sm); padding:9px 12px; font-size:13px; color:var(--app-text); }
.br-tree b { font-weight:700; }
.br-tree .facts { color:var(--app-muted); font-variant-numeric:tabular-nums; }
.br-tree a { color:var(--app-accent); }
.br-credit { color:var(--app-muted); font-size:12px; margin-top:18px; }

/* Primary actions wear the gold in both modes; secondary ones are quiet outlines. */
.stButton button[kind="primary"], .stDownloadButton button[kind="primary"] {
  background:var(--app-gold); color:var(--app-gold-ink); border:0; font-weight:700; border-radius:var(--app-radius-sm);
  min-height:44px; box-shadow:0 1px 2px rgba(2,58,36,.12); }
.stButton button[kind="primary"]:hover { background:var(--app-gold-deep); color:var(--app-gold-ink); }
.stButton button[kind="primary"]:disabled { opacity:.5; }
.stButton button[kind="secondary"], .stDownloadButton button[kind="secondary"] {
  border-radius:var(--app-radius-sm); min-height:44px; }

@media (max-width: 640px) {
  .block-container { padding-left:.9rem; padding-right:.9rem; padding-top:1rem; }
  .br-appbar { padding:8px 12px; gap:8px; }
  .br-wordmark { font-size:16px; }
  .br-step { padding:5px 10px; }
  .br-step .long { display:none; }
  .br-step .short { display:inline; }
  .st-key-br-card { padding:14px 14px; }
  .br-h { font-size:16.5px; }
  .br-metric { min-width:0; padding:8px 10px; }
  .br-metric .num { font-size:18px; }
  .st-key-br-card [data-testid="stElementContainer"]:has(.stButton),
  .st-key-br-card .stButton, .st-key-br-card .stButton button { width:100% !important; }
  .br-row { flex-wrap:wrap; }
  .br-k { white-space:normal; }
}
</style>
"""

MODE_JS = """
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
"""


def install_theme() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    components.html(MODE_JS, height=0)


def _inline_svg(name: str, cls: str) -> str:
    """A committed brand SVG, inlined so it needs no static file route; the credit <desc> stays in it."""
    svg = (BRAND_DIR / name).read_text().strip()
    return svg.replace("<svg ", f'<svg class="{cls}" ', 1)


def header(chain_name: str, paused: bool) -> None:
    """Mark, wordmark and the live-chain chip. The view toggle sits beside it (see app.py)."""
    st.markdown(
        '<div class="br-appbar">'
        + _inline_svg("mark.svg", "br-mark-light") + _inline_svg("mark-reverse.svg", "br-mark-dark")
        + '<span class="br-wordmark">BioRig<span class="dot">.</span></span>'
        + f'<span class="br-chip{" paused" if paused else ""}"><span class="d"></span>{html.escape(chain_name)}</span>'
        + "</div>",
        unsafe_allow_html=True,
    )


def rows_html(rows: list[tuple[str, str]], plain: bool = False) -> str:
    cls = "br-v plain" if plain else "br-v"
    return "".join(f'<div class="br-row"><span class="br-k">{html.escape(k)}</span>'
                   f'<span class="{cls}">{v}</span></div>' for k, v in rows)


def pill(ok: bool, yes: str, no: str) -> str:
    return f'<span class="br-pill {"br-ok" if ok else "br-bad"}">{html.escape(yes if ok else no)}</span>'


def credit() -> None:
    st.caption(t("credit"))
