"""Drive the running Streamlit dashboard in headless Chromium: both modes, 1440 and 390 px wide.

    .venv/bin/python scripts/check_dashboard_ui.py http://localhost:8501

Two views per mode and width. The planter flow (the default view) is walked end to end: the branded header and the
favicon, step 1's computed biomass, step 2 with the browser's geolocation granted (a fixed position handed to
Chromium, since the gate has no GPS) and the plot's free/taken status, and step 3's pre-flight check. Its expected
verdict is read from the chain at run time, like the operator checks below; the register control is never pressed.
None of the protocol terms the planter flow replaced may appear on it.

The operator view (?view=operator) asserts the live proxy, chain id, getTreeStats rows and the TBA cross-check are visible, the console is clean,
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

# The planter flow, located by the browser's geolocation at a fixed position with the default plot reference.
GEO = {"latitude": -1.2864, "longitude": 36.8172}
planter_plot = h3_nullifier.derive(GEO["latitude"], GEO["longitude"], "plot-1")
planter_taken = Chain(settings).is_nullifier_active(planter_plot.nullifier)
planter_status = "This plot already has a tree registered on it." if planter_taken else "This plot is free."
planter_verdict = "Not this one." if planter_taken else "Ready."
print(f"planter flow: GPS {GEO['latitude']}, {GEO['longitude']} plot-1 active={planter_taken} -> "
      f"expect '{planter_status}' then '{planter_verdict}'")
JARGON = ("spatialNullifier", "keccak", "eth_call", "VERIFIER_ROLE", "H3 res", "NullifierInUse", "tbaAddress",
          "mintTree", "initialDBH", "initialBiomass", "would revert")
TEXT_JS = "want => document.body.innerText.includes(want)"


def planter_pass(page) -> list[str]:
    """Walk the three steps; return what was missing or wrong."""
    missing = []

    def wait_text(text, timeout=90_000):
        try:
            page.wait_for_function(TEXT_JS, arg=text, timeout=timeout)
            return True
        except PlaywrightTimeout:
            missing.append(text)
            return False

    if not wait_text("How thick is the trunk?"):
        return missing
    wait_text("Tree #1")  # the live tree badges
    header = page.evaluate("""() => { const bar = document.querySelector('.br-appbar');
        return bar ? [!!bar.querySelector('svg[aria-label^="BioRig brandmark"]'), bar.innerText] : null; }""")
    if not header or not header[0] or "BioRig" not in header[1] or settings.chain_name not in header[1]:
        missing.append(f"branded header with mark, wordmark and '{settings.chain_name}' chip: got {header}")
    icon = page.evaluate("""async () => { const l = document.querySelector('link[rel~="icon"]');
        if (!l) return null; const r = await fetch(l.href); return [l.href, r.status, r.headers.get('content-type')]; }""")
    if not icon or icon[1] != 200 or "image/png" not in (icon[2] or "") or "favicon.ico" in icon[0]:
        missing.append(f"brand favicon served as PNG: got {icon}")
    for text in ("208", "359", "Chave et al. 2014"):
        wait_text(text, 10_000)
    page.get_by_role("button", name="Continue →").click()
    if not wait_text("Where is the tree?"):
        return missing
    try:
        page.frame_locator("iframe[title='dashboard.geolocate.biorig_geolocate']").get_by_role("button").click(
            timeout=30_000)
    except PlaywrightTimeout:
        missing.append("geolocation button")
        return missing
    wait_text("Your phone's GPS", 30_000)
    wait_text(f"{GEO['latitude']:.6f}, {GEO['longitude']:.6f}", 30_000)
    wait_text(planter_status)
    page.get_by_role("button", name="Continue →").click()
    if not wait_text("Check this tree"):
        return missing
    page.get_by_role("button", name="Check this tree →").click()
    wait_text(planter_verdict, 120_000)
    body = page.evaluate("document.body.innerText")
    if ("Ready." in body) == ("Not this one." in body):
        missing.append("exactly one pre-flight verdict")
    missing += [f"jargon on the planter flow: {j}" for j in JARGON if j in body]
    return missing


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
        for width in (1440, 390):
            context = browser.new_context(viewport={"width": width, "height": 900}, color_scheme=scheme,
                                          geolocation=GEO, permissions=["geolocation"])
            page = context.new_page()
            errors = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            p_missing = planter_pass(page)
            p_overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
            p_mode = page.evaluate("document.documentElement.getAttribute('data-app-mode')")
            p_status = "ok"
            if p_missing or errors or p_mode != scheme or p_overflow:
                p_status = "FAIL"
                failures.append(("planter", scheme, width, p_missing, errors[:3], p_mode, p_overflow))
            print(f"  planter  {scheme:5} {width:4}px  mode={p_mode}  missing={p_missing}  "
                  f"console_errors={len(errors)}  h-overflow={p_overflow}  {p_status}")
            page.goto(url.rstrip("/") + "/?view=operator")
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
            print(f"  operator {scheme:5} {width:4}px  mode={mode}  missing={missing}  console_errors={len(errors)}  "
                  f"h-overflow={overflow}  key_in_page={bool(key and key in html)}  {status}")
            context.close()
    browser.close()
if failures:
    print("UI CHECK FAILED", failures)
    sys.exit(1)
print("UI CHECK OK")
