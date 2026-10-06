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
.br-chip.paused .d { background:var(--app-warn);
