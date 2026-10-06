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
  --app-bg: #F6F8F4; --app-surface: #FFFFFF; --app-surface-2: #EFF4EE; --app-field: #F3F7F2; --app-rule: #DCE7DD;
  --app-text: #0B1F16; --app-muted: #586B60; --app-accent: #0A5B3A; --app-accent-text: #FFFFFF;
  --app-lime: #35D07F; --app-lime-deep: #2BBF71; --app-lime-ink: #04120C; --app-lime-ring: rgba(53,208,127,.35);
  --app-lime-text: #0E7A4A; --app-emerald: #0E7A4A; --app-glow: 0 1px 2px rgba(2,58,36,.14);
  --app-hero-glow: rgba(53,208,127,.14);
  --app-gold: #FCFF52; --app-gold-deep: #E8EC2A; --app-gold-ink: #1A1C00; --app-gold-ring: rgba(252,255,82,.45);
  --app-gold-text: #6B5F00;
  --app-forest: #023A24; --app-wordmark: #023A24;
  --app-chip-bg: #E6F2E9; --app-chip-text: #0A5B3A; --app-step-n: #E8EEE7;
  --app-ok: #1F7A3D; --app-ok-bg: #EAF3EC; --app-ok-rule: #CDE3D3;
  --app-warn: #8A6D00; --app-warn-bg: #FBF6E4; --app-warn-rule: #EADFB4;
  --app-bad: #B42318; --app-bad-bg: #FBE7E5;
  --app-plot-a: #E8EFE6; --app-plot-b: #DCE7DA; --app-plot-grid: rgba(2,58,36,.07);
  --app-plot-cell: rgba(53,208,127,.30); --app-plot-line: #023A24; --app-plot-faint: rgba(2,58,36,.18);
  --app-font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
  --app-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  --app-radius: 18px; --app-radius-sm: 14px; --app-shadow: 0 1px 3px rgba(2,58,36,.05);
}
html[data-app-mode="dark"] {
  --app-bg: #04120C; --app-surface: #0A1F16; --app-surface-2: #0D281A; --app-field: #071A10;
  --app-rule: rgba(53,208,127,.17);
  --app-text: #EAF4EC; --app-muted: #9DB4A6; --app-accent: #35D07F; --app-accent-text: #04120C;
  --app-lime-text: #35D07F; --app-glow: 0 6px 20px rgba(53,208,127,.2); --app-hero-glow: rgba(53,208,127,.16);
  --app-gold-ring: rgba(252,255,82,.28); --app-gold-text: #FCFF52; --app-wordmark: #EAF4EC;
  --app-chip-bg: #0D281A; --app-chip-text: #35D07F; --app-step-n: #12301F;
  --app-ok: #8FE0AC; --app-ok-bg: #0B2619; --app-ok-rule: rgba(53,208,127,.22);
  --app-warn: #E8C547; --app-warn-bg: #2A2410; --app-warn-rule: #4A3F18;
  --app-bad: #F87171; --app-bad-bg: #3A1414;
  --app-plot-a: #0A2117; --app-plot-b: #071A10; --app-plot-grid: rgba(234,244,236,.06);
  --app-plot-cell: rgba(252,255,82,.22); --app-plot-line: #FCFF52; --app-plot-faint: rgba(234,244,236,.16);
  --app-shadow: none;
}
.block-container { padding-top: 4.25rem; max-width: 1240px; }
.stMarkdown p, .stMarkdown li { font-size: 15px; }
[data-testid="stHeadingWithActionElements"] h3 { letter-spacing: -.02em; font-weight: 700; }

[data-testid="stSlider"] { direction: ltr; }

.br-appbar { display:flex; align-items:center; gap:10px 14px; flex-wrap:wrap; min-height:50px;
  background:var(--app-surface); border:1px solid var(--app-rule); border-radius:var(--app-radius-sm);
  padding:9px 16px; box-shadow:var(--app-shadow); }
.br-appbar svg { flex:none; }
.br-wordmark { font:700 19px/1 var(--app-font); letter-spacing:-.03em; color:var(--app-wordmark); }
.br-wordmark .dot { color:var(--app-gold-deep); }
html[data-app-mode="dark"] .br-mark-light, html:not([data-app-mode="dark"]) .br-mark-dark { display:none; }
.br-chip { font:600 11.5px/1 var(--app-font); padding:6px 10px; border-radius:99px; background:var(--app-chip-bg);
  color:var(--app-chip-text); display:inline-flex; align-items:center; gap:6px; white-space:nowrap; }
.br-chip .d { width:7px; height:7px; border-radius:50%; background:var(--app-lime);
  box-shadow:0 0 0 3px var(--app-lime-ring); }
.br-chip.paused .d { background:var(--app-warn); box-shadow:none; }
.st-key-br-view [data-testid="stWidgetLabel"] { display:none; }
.st-key-br-view { align-self:flex-end; }
.st-key-br-view button { border-radius:99px !important; font-weight:600; }
.st-key-br-view button[aria-checked="true"] { background:var(--app-lime) !important;
  border-color:var(--app-lime) !important; color:var(--app-lime-ink) !important; box-shadow:var(--app-glow); }
.st-key-br-view button[aria-checked="true"] * { color:var(--app-lime-ink) !important; }

.st-key-br-hero { position:relative; overflow:hidden; border:1px solid var(--app-rule) !important;
  border-radius:var(--app-radius) !important; padding:34px 34px 26px; margin-top:14px;
  background-image:linear-gradient(var(--app-plot-grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--app-plot-grid) 1px, transparent 1px),
    radial-gradient(ellipse at 88% 0%, var(--app-hero-glow), transparent 58%),
    linear-gradient(160deg, var(--app-surface), var(--app-bg) 70%);
  background-size:26px 26px, 26px 26px, auto, auto; }
.br-hero-lockup { display:flex; align-items:center; gap:10px; margin-bottom:22px; }
.br-hero-lockup svg { width:46px; height:46px; flex:none; }
.br-hero-lockup .br-wordmark { font-size:25px; }
.br-kicker { font:700 11.5px/1.3 var(--app-font); letter-spacing:.14em; text-transform:uppercase;
  color:var(--app-lime-text); }
.stMarkdown h1.br-h1 { font:700 46px/1.08 var(--app-font); letter-spacing:-.035em; color:var(--app-text);
  margin:12px 0 14px; padding:0; max-width:19ch; }
.br-h1 em { font-style:normal; color:var(--app-lime-text); }
.stMarkdown p.br-sub { color:var(--app-muted); font-size:16.5px; line-height:1.55; max-width:60ch; margin:0; }
.st-key-br-ctas { margin-top:10px; flex-wrap:wrap; }
.st-key-br-ctas button { min-height:52px !important; padding:0 24px !important; border-radius:12px !important; }
.st-key-br-ctas button p { font-size:15px !important; font-weight:700; }
.st-key-br-cta-protocol button { background:transparent; border:1px solid var(--app-rule); color:var(--app-text); }
.st-key-br-cta-protocol button:hover { border-color:var(--app-lime); color:var(--app-text);
  box-shadow:0 0 0 3px var(--app-lime-ring); }
.br-strip { display:flex; gap:10px; flex-wrap:wrap; margin-top:12px; }
.br-kpi { flex:1; min-width:150px; background:var(--app-surface); border:1px solid var(--app-rule);
  border-radius:var(--app-radius-sm); padding:12px 14px; }
.br-kpi .lab, .br-label, .br-metric .lab { font:700 10.5px/1.3 var(--app-font); text-transform:uppercase;
  letter-spacing:.1em; color:var(--app-muted); }
.br-kpi .v { font:700 19px/1.25 var(--app-mono); letter-spacing:-.02em; margin-top:5px; color:var(--app-text);
  font-variant-numeric:tabular-nums; overflow-wrap:anywhere; }
.br-kpi .v.gold { color:var(--app-gold-text); }
.br-sect { margin:34px 0 0; }
.br-cards { display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:14px; margin-top:12px; }
.br-card { background:var(--app-surface); border:1px solid var(--app-rule); border-radius:var(--app-radius-sm);
  padding:20px; }
.br-card .ic { width:32px; height:32px; border-radius:10px; background:var(--app-surface-2);
  color:var(--app-lime-text); font:700 13px/32px var(--app-mono); text-align:center; margin-bottom:14px;
  box-shadow:inset 0 0 0 1px var(--app-lime-ring); }
.br-card .tt, .br-how-step .tt { font:700 16px/1.3 var(--app-font); letter-spacing:-.01em; color:var(--app-text);
  margin-bottom:6px; }
.stMarkdown .br-card p, .stMarkdown .br-how-step p { margin:0; color:var(--app-muted); font-size:14px;
  line-height:1.55; }
.br-card .eg { margin-top:14px; padding-top:10px; border-top:1px solid var(--app-rule);
  font:600 12.5px/1.4 var(--app-mono); font-variant-numeric:tabular-nums; color:var(--app-gold-text); }
.br-how { display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:0 26px; margin-top:12px;
  border-top:2px solid var(--app-lime); }
.br-how-step { padding:14px 0 4px; }
.br-how-step .tt { font-size:15px; }

.br-bar { display:flex; flex-wrap:wrap; align-items:center; gap:6px 14px; padding:10px 15px;
  background:var(--app-surface); border:1px solid var(--app-rule); border-radius:var(--app-radius-sm);
  font:12.5px/1.5 var(--app-font); color:var(--app-muted); margin-bottom:6px; }
.br-bar b { color:var(--app-text); font-weight:600; }
.br-bar .mono { font-family:var(--app-mono); font-variant-numeric:tabular-nums; color:var(--app-text);
  overflow-wrap:anywhere; }
.br-dot { width:9px; height:9px; border-radius:50%; background:var(--app-lime); display:inline-block;
  box-shadow:0 0 0 3px var(--app-lime-ring); }
.br-panel { background:var(--app-surface); border:1px solid var(--app-rule); border-radius:var(--app-radius-sm);
  padding:12px 16px; margin:4px 0 14px; box-shadow:var(--app-shadow); }
.br-label { margin-bottom:6px; }
.br-row { display:flex; justify-content:space-between; gap:12px; padding:7px 0;
  border-bottom:1px solid var(--app-rule); font-size:13.5px; }
.br-row:last-child { border-bottom:0; }
.br-k { color:var(--app-muted); font-family:var(--app-font); white-space:nowrap; }
.br-v { color:var(--app-text); font-family:var(--app-mono); font-size:12.5px; font-variant-numeric:tabular-nums;
  text-align:right; overflow-wrap:anywhere; min-width:0; }
.br-v.plain { font-family:var(--app-font); font-size:13.5px; font-weight:600; }
.br-v .mono { font-family:var(--app-mono); font-size:12.5px; font-weight:500; }
.br-pill { font:600 10.5px/1 var(--app-font); padding:4px 9px; border-radius:99px; display:inline-block; }
.br-ok { background:var(--app-ok-bg); color:var(--app-ok); }
.br-bad { background:var(--app-bad-bg); color:var(--app-bad); }
.br-links a, a.br-link, .br-tree a { color:var(--app-accent) !important; margin-right:12px; font-size:13px; }
.br-null { font-family:var(--app-mono); font-size:12px; color:var(--app-text); background:var(--app-field);
  border:1px solid var(--app-rule); border-radius:var(--app-radius-sm); padding:8px 10px; overflow-wrap:anywhere; }

.br-steps { display:flex; gap:8px; align-items:center; margin:14px 0 6px; flex-wrap:wrap; }
.br-step { display:flex; align-items:center; gap:8px; font:600 12.5px/1.2 var(--app-font); color:var(--app-muted);
  background:var(--app-surface); border:1px solid var(--app-rule); border-radius:99px; padding:7px 13px; }
.br-step .n { width:19px; height:19px; border-radius:50%; background:var(--app-step-n); color:var(--app-muted);
  font:700 11px/19px var(--app-mono); text-align:center; flex:none; }
.br-step.on { color:var(--app-text); border-color:var(--app-lime); box-shadow:0 0 0 3px var(--app-lime-ring); }
.br-step.on .n { background:var(--app-lime); color:var(--app-lime-ink); }
.br-step.done .n { background:var(--app-gold); color:var(--app-gold-ink); }
.br-step .short { display:none; }
.st-key-br-card { background:var(--app-surface); border:1px solid var(--app-rule) !important;
  border-radius:var(--app-radius) !important; padding:22px 24px; box-shadow:var(--app-shadow); }
.br-h { font:700 21px/1.25 var(--app-font); letter-spacing:-.02em; color:var(--app-text); margin:0 0 4px; }
.stMarkdown p.br-lede { color:var(--app-muted); font-size:15px; margin:0 0 6px; }
.stMarkdown p.br-note { color:var(--app-muted); font-size:13.5px; margin:8px 0 0; }
.br-metrics { display:flex; gap:12px; flex-wrap:wrap; margin:6px 0 2px; }
.br-metric { flex:1; min-width:112px; background:var(--app-field); border:1px solid var(--app-rule);
  border-radius:var(--app-radius-sm); padding:12px 14px; }
.br-metric .num { font:700 22px/1.3 var(--app-mono); letter-spacing:-.02em; color:var(--app-text);
  font-variant-numeric:tabular-nums; margin-top:3px; }
.br-metric .num small { font:600 12px var(--app-font); color:var(--app-muted); }
.br-status { display:flex; gap:10px; align-items:flex-start; background:var(--app-ok-bg);
  border:1px solid var(--app-ok-rule); border-radius:var(--app-radius-sm); padding:12px 14px; font-size:14px;
  color:var(--app-text); margin:8px 0 4px; }
.br-status .ic { font-weight:700; color:var(--app-ok); flex:none; }
.br-status.warn { background:var(--app-warn-bg); border-color:var(--app-warn-rule); }
.br-status.warn .ic { color:var(--app-warn); }
.br-status.idle { background:var(--app-field); border-color:var(--app-rule); color:var(--app-muted); }
.br-status.idle .ic { color:var(--app-muted); }
.br-status a { color:var(--app-accent); }
.br-plot { position:relative; border-radius:var(--app-radius-sm); border:1px solid var(--app-rule); overflow:hidden;
  background-image:linear-gradient(var(--app-plot-grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--app-plot-grid) 1px, transparent 1px),
    linear-gradient(160deg, var(--app-plot-a), var(--app-plot-b) 55%, var(--app-plot-a));
  background-size:26px 26px, 26px 26px, auto; }
.br-plot svg { display:block; width:100%; height:auto; }
.br-trees { display:flex; gap:10px; flex-wrap:wrap; }
.br-tree { display:flex; align-items:center; gap:10px; background:var(--app-surface); border:1px solid var(--app-rule);
  border-radius:var(--app-radius-sm); padding:10px 14px; font-size:13.5px; color:var(--app-text); }
.br-tree b { font-weight:700; }
.br-tree .facts { color:var(--app-muted); font-family:var(--app-mono); font-size:12.5px;
  font-variant-numeric:tabular-nums; }
.br-tree a { color:var(--app-accent); }
.br-credit { color:var(--app-muted); font-size:12px; margin-top:18px; }

.stButton button[kind="primary"], .stDownloadButton button[kind="primary"] {
  background:var(--app-lime); color:var(--app-lime-ink); border:0; font-weight:700;
  border-radius:var(--app-radius-sm); min-height:44px; box-shadow:var(--app-glow); }
.stButton button[kind="primary"] *, .stDownloadButton button[kind="primary"] * { color:var(--app-lime-ink); }
.stButton button[kind="primary"]:hover { background:var(--app-lime-deep); color:var(--app-lime-ink); }
.stButton button[kind="primary"]:disabled { opacity:.5; box-shadow:none; }
.stButton button[kind="secondary"], .stDownloadButton button[kind="secondary"] {
  border-radius:var(--app-radius-sm); min-height:44px; }

@media (max-width: 640px) {
  .block-container { padding-left:.9rem; padding-right:.9rem; padding-top:1rem; }
  .br-appbar { padding:8px 12px; gap:8px; }
  .br-wordmark { font-size:16px; }
  .st-key-br-view { align-self:flex-start; }
  .st-key-br-hero { padding:22px 18px 18px; }
  .br-hero-lockup { margin-bottom:16px; }
  .br-hero-lockup svg { width:36px; height:36px; }
  .br-hero-lockup .br-wordmark { font-size:20px; }
  .stMarkdown h1.br-h1 { font-size:30px; }
  .stMarkdown p.br-sub { font-size:15px; }
  .st-key-br-ctas { flex-direction:column; }
  .st-key-br-ctas [data-testid="stElementContainer"], .st-key-br-ctas .stButton,
  .st-key-br-ctas .stButton button { width:100% !important; }
  .br-kpi { min-width:0; flex:1 1 40%; }
  .br-kpi .v { font-size:15.5px; }
  .br-step { padding:5px 10px; }
  .br-step .long { display:none; }
  .br-step .short { display:inline; }
  .st-key-br-card { padding:16px 14px; }
  .br-h { font-size:17.5px; }
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
    if (doc.documentElement.getAttribute('data-app-mode') !== want) {
        doc.documentElement.setAttribute('data-app-mode', want);
    }
    doc.documentElement.setAttribute('dir', 'ltr');
    doc.body.setAttribute('dir', 'ltr');
    doc.documentElement.style.direction = 'ltr';
  }
  mode();
  new MutationObserver(mode).observe(doc.body, {attributes: true, subtree: true, attributeFilter: ['class', 'style', 'dir']});
})();
</script>
"""

def install_theme() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    components.html(MODE_JS, height=0)

def inline_svg(name: str, cls: str) -> str:
    svg = (BRAND_DIR / name).read_text().strip()
    return svg.replace("<svg ", f'<svg class="{cls}" ', 1)

def header(chain_name: str, paused: bool) -> None:
    st.markdown(
        '<div class="br-appbar">'
        + inline_svg("mark.svg", "br-mark-light") + inline_svg("mark-reverse.svg", "br-mark-dark")
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
