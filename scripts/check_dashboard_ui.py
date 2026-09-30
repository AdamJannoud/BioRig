"""Drive the running Streamlit dashboard in headless Chromium: both modes, 1280 and 390 px wide.

    .venv/bin/python scripts/check_dashboard_ui.py http://localhost:8501

Asserts the live proxy, chain id, getTreeStats rows, the TBA cross-check and a successful eth_call simulation are
visible, the console is clean, data-app-mode follows the theme, and the verifier key is not in the page.
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dashboard.config import load_settings  # noqa: E402

url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8501"
settings = load_settings()
key = (settings.private_key or "").lower().removeprefix("0x")
expect = ["0x21ab8B36177F65ce69e04e281E4aFf3Db6b5f7E6", "11142220", "getTreeStats(1)", "spatialNullifier",
          "0x61bd8BEcE5a38209Fc10d4DA3f837EE83a10124a", "match ✓", "would succeed", "VERIFIER_ROLE ✓"]
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
