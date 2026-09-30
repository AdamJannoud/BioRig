"""Entrypoint for Streamlit Community Cloud and Hugging Face Spaces.

Both platforms run `streamlit_app.py` in the repository root by default, so this file exists to make the
default one-click deploy work. It runs the real dashboard rather than a copy of it:

    .venv/bin/streamlit run dashboard/app.py     # exactly equivalent, locally

Configuration comes from the app's Secrets (RPC_URL, CHAIN_ID, PRIVATE_KEY, ALLOW_MINT, ...); see
DEPLOY_DASHBOARD.md. Nothing else has to be set: the chain id, RPC endpoint and proxy address all have
committed static fallbacks, so the page renders even with no secrets at all.
"""
from __future__ import annotations

import runpy
from pathlib import Path

DASHBOARD_APP = Path(__file__).resolve().parent / "dashboard" / "app.py"

runpy.run_path(str(DASHBOARD_APP), run_name="__main__")
