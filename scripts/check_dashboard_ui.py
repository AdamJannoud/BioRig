"""Drive the running Streamlit dashboard in headless Chromium: both modes, 1280 and 390 px wide.

    .venv/bin/python scripts/check_dashboard_ui.py http://localhost:8501

Asserts the live proxy, chain id, getTreeStats rows, the TBA cross-check and a successful eth_call simulation are
visible, the console is clean, data-app-mode follows the theme, and the verifier key is not in the page.

The expected chain and proxy are the dashboard's own configuration (CHAIN_ID from the environment or .env, else the
repo default), so run it with the same CHAIN_ID the dashboard was started with. Token #1's token-bound account is
pinned where a deployment's real value is known; on any other chain it is read from getTreeStats(1) directly.
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dashboard.config import load_settings  # noqa: E402

# Token #1's TBA, read from chain once per real deployment and pinned, so the page is checked against a known value.
KNOWN_TBA_1 = {11142220: "0x61bd8BEcE5a38209Fc10d4DA3f837EE83a10124a"}

url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8501"
settings = load_settings()
key = (settings.private_key or "").lower().removeprefix("0x")


def tba_1() -> str:
    if settings.chain_id in KNOWN_TBA_1:
        return KNOWN_TBA_1[settings.chain_id]
    from dashboard.chain import Chain

    return Chain(settings).get_tree_stats(1).tba_address


from web3 import Web3  # noqa: E402

print(f"expecting {settings.chain_name} ({settings.chain_id}), proxy {settings.proxy.address}")
expect = [Web3.to_checksum_address(settings.proxy.address), str(settings.chain_id), "getTreeStats(1)",
          "spatialNullifier", Web3.to_checksum_address(tba_1()), "match ✓", "would succeed", "VERIFIER_ROLE ✓"]
failures = []
with sync_playwright() as p:
    browser = p.chromium.launch(args=["--num-raster-threads=4"])
    for scheme in ("dark", "light"):
        for width in (1280, 390):
            page = browser.new_page(viewport={"width": width, "height": 900}, color_scheme=scheme)
            errors = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.goto(url)
            page.wait_for_function("document.body.innerText.includes('match ✓') && "
                                   "document.body.innerText.includes('would succeed')", timeout=120_000)
            body = page.evaluate("document.body.innerText")
            html = page.content().lower()
            mode = page.evaluate("document.documentElement.getAttribute('data-app-mode')")
            missing = [e for e in expect if e not in body]
            overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
            status = "ok"
            if missing or errors or mode != scheme or (key and key in html) or overflow:
                status = "FAIL"
                failures.append((scheme, width, missing, errors[:3], mode, overflow))
            print(f"  {scheme:5} {width:4}px  mode={mode}  missing={missing}  console_errors={len(errors)}  "
                  f"h-overflow={overflow}  key_in_page={bool(key and key in html)}  {status}")
            page.close()
    browser.close()
if failures:
    print("UI CHECK FAILED", failures)
    sys.exit(1)
print("UI CHECK OK")
