"""Drive the running Streamlit dashboard in headless Chromium: both modes, 1280 and 390 px wide.

    .venv/bin/python scripts/check_dashboard_ui.py http://localhost:8501

Asserts the live proxy, chain id, getTreeStats rows and the TBA cross-check are visible, the console is clean,
data-app-mode follows the theme, and the verifier key is not in the page. The eth_call simulation is checked twice:
- the untouched default form (the pilot plot) must show the verdict the chain implies: "would revert" with
  NullifierInUse once that nullifier is active, "would succeed" while it is not;
- a per-run unique salt typed into the form (a fresh tree in the same H3 cell) must show "would succeed" with a
  tokenId and a gas estimate.

The expected chain and proxy are the dashboard's own configuration (CHAIN_ID from the environment or .env, else the
repo default), so run it with the same CHAIN_ID the dashboard was started with. Token #1's token-bound account is
pinned where a deployment's real value is known; on any other chain it is read from getTreeStats(1) directly.
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dashboard import h3_nullifier  # noqa: E402
from dashboard.config import load_settings  # noqa: E402

# Token #1's TBA, read from chain once per real deployment and pinned, so the page is checked against a known value.
KNOWN_TBA_1 = {11142220: "0x61bd8BEcE5a38209Fc10d4DA3f837EE83a10124a",
               42220: "0x453e89520DB8f374CFCeA95625B99DF5d4F1256A"}

url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8501"
settings = load_settings()
key = (settings.private_key or "").lower().removeprefix("0x")


def tba_1() -> str:
    if settings.chain_id in KNOWN_TBA_1:
        return KNOWN_TBA_1[settings.chain_id]
    from dashboard.chain import Chain

    return Chain(settings).get_tree_stats(1).tba_address


from web3 import Web3  # noqa: E402
from dashboard.chain import Chain  # noqa: E402

# The form defaults in dashboard/app.py; the verdict they must render is whatever the chain says about them now.
DEFAULT_FORM = dict(lat=-1.2921, lng=36.8219, salt="plot-1", resolution=h3_nullifier.DEFAULT_RESOLUTION)
default = h3_nullifier.derive(**DEFAULT_FORM)
default_active = Chain(settings).is_nullifier_active(default.nullifier)
fresh_salt = f"ui-check-{int(time.time())}"
fresh = h3_nullifier.derive(**{**DEFAULT_FORM, "salt": fresh_salt})
assert not Chain(settings).is_nullifier_active(fresh.nullifier), f"salt {fresh_salt} is already minted"

print(f"expecting {settings.chain_name} ({settings.chain_id}), proxy {settings.proxy.address}")
print(f"default-form nullifier {default.nullifier_hex} active={default_active} -> "
      f"expect {'would revert: NullifierInUse' if default_active else 'would succeed'}; fresh salt {fresh_salt}")
expect = [Web3.to_checksum_address(settings.proxy.address), str(settings.chain_id), "getTreeStats(1)",
          "spatialNullifier", Web3.to_checksum_address(tba_1()), "match ✓", "VERIFIER_ROLE ✓"]

# Verdict predicates over the simulation panel's rows (each .br-panel's innerText is "key\tvalue" lines), so a
# "tokenId" elsewhere on the page or a stale panel from the previous render cannot satisfy them.
VERDICT_JS = r"""([want, nullifierHex]) => {
  const body = document.body.innerText;
  if (!body.includes(nullifierHex)) return false;
  const panels = Array.from(document.querySelectorAll('.br-panel')).map(e => e.innerText);
  const ok = panels.some(t => /would succeed/.test(t) && /tokenId\s+#\d+/.test(t)
                              && /gas estimate\s+[1-9][\d,]*/.test(t));
  const revert = panels.some(t => /would revert/.test(t) && /error\s+[^\n]*NullifierInUse/.test(t));
  const anyRevert = panels.some(t => /would revert/.test(t));
  return want === 'succeed' ? ok && !anyRevert : revert && !ok;
}"""
default_want = "revert" if default_active else "succeed"


def wait_verdict(page, want: str, nullifier_hex: str) -> bool:
    try:
        page.wait_for_function(VERDICT_JS, arg=[want, nullifier_hex], timeout=120_000)
        return True
    except PlaywrightTimeout:
        return False

failures = []
with sync_playwright() as p:
    browser = p.chromium.launch(args=["--num-raster-threads=4"])
    for scheme in ("dark", "light"):
        for width in (1280, 390):
            page = browser.new_page(viewport={"width": width, "height": 900}, color_scheme=scheme)
            errors = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.goto(url)
            # The panels fill in independently (getTreeStats can land after the TBA check on a slow RPC), so wait for
            # every expected string; whatever is still absent at the timeout is reported as missing below.
            try:
                page.wait_for_function("want => want.every(e => document.body.innerText.includes(e))", arg=expect,
                                       timeout=120_000)
            except PlaywrightTimeout:
                pass
            body = page.evaluate("document.body.innerText")
            missing = [e for e in expect if e not in body]
            if not wait_verdict(page, default_want, default.nullifier_hex):
                missing.append(f"default form: would {default_want}")
            # A new tree in the same cell: type a fresh salt and commit it with Enter, which is when Streamlit reruns.
            try:
                salt_box = page.get_by_label("salt", exact=True)
                salt_box.fill(fresh_salt, timeout=30_000)
                salt_box.press("Enter")
                fresh_ok = wait_verdict(page, "succeed", fresh.nullifier_hex)
            except PlaywrightTimeout:
                fresh_ok = False
            if not fresh_ok:
                missing.append(f"fresh salt {fresh_salt}: would succeed + tokenId + gas estimate")
            html = page.content().lower()
            mode = page.evaluate("document.documentElement.getAttribute('data-app-mode')")
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
