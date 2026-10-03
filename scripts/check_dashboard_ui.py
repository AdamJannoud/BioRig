"""Drive the running Streamlit dashboard in headless Chromium: both modes, 1440 and 390 px wide.

    .venv/bin/python scripts/check_dashboard_ui.py http://localhost:8501

Three views per mode and width, twelve renders in all, each reached the way a visitor reaches it: from the bare URL.

Home (the default view) is asserted first: the branded header and the favicon, the hero, both calls to action, the
three Why-Celo cards and the live strip (the chain id, the tree count, the pilot registration's cost and the proxy),
and none of the protocol terms. In light mode no text on any screen may be painted in the lime (#35D07F measures
1.9:1 on white, so there it is a fill or a rule only).

The planter flow is entered from home's "Register a tree" call to action and walked end to end: the header, step 1's
computed biomass, step 2 with the browser's geolocation granted (a fixed position handed to
Chromium, since the gate has no GPS) and the plot's free/taken status, and step 3's pre-flight check. Its expected
verdict is read from the chain at run time, like the operator checks below; the register control is never pressed.
None of the protocol terms the planter flow replaced may appear on it.

The operator view, entered from home's "See the live on-chain assets" call to action, asserts the live proxy, chain id, getTreeStats rows and the TBA cross-check are visible, the console is clean,
data-app-mode follows the theme, and the verifier key is not in the page. The eth_call simulation is checked twice:
- the untouched default form (the pilot plot) must show the verdict the chain implies: "would revert" with
  NullifierInUse once that nullifier is active, "would succeed" while it is not;
- a per-run unique salt typed into the form (a fresh tree in the same H3 cell) must show "would succeed" with a
  tokenId and a gas estimate.

The expected chain and proxy are the dashboard's own configuration (CHAIN_ID from the environment or .env, else the
repo default), so run it with the same CHAIN_ID the dashboard was started with. Token #1's token-bound account is
pinned where a deployment's real value is known; on any other chain it is read from getTreeStats(1) directly.

The published ?view=planter and ?view=operator links are opened once at the end: they must still land on the planter
flow and the operator view (they are aliases of ?view=register and ?view=protocol).
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
# Key-free (the gate's VERIFY_ALLOW_NO_KEY=1, as in CI): with no signer the dashboard is read-only by design, so the
# simulation verdicts cannot render. The check then asserts the read-only state in their place and says so; the
# gate lists step 4-sim as skipped, so the run is never reported as a full pass.
NO_KEY = not key
READ_ONLY_PLANTER = "Read-only — you can look, not register."
READ_ONLY_OPERATOR = "PRIVATE_KEY is not set in .env, so the verifier account is unavailable."
expect = [Web3.to_checksum_address(settings.proxy.address), str(settings.chain_id), "getTreeStats(1)",
          "spatialNullifier", Web3.to_checksum_address(tba_1()), "match ✓",
          *(("no VERIFIER_ROLE", READ_ONLY_OPERATOR) if NO_KEY else ("VERIFIER_ROLE ✓",))]
if NO_KEY:
    print("no PRIVATE_KEY: the simulation verdicts are not exercised; asserting the read-only state instead")

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
# Skipping "Use my location" leaves the planter on the default plot, which the dashboard picks from the chain (the
# first free reference in the pilot cell); the status it must show is whatever the chain says about that same plot.
from dashboard import planter_view  # noqa: E402
default_ref = planter_view.default_reference(Chain(settings).is_nullifier_active)
default_plot = h3_nullifier.derive(planter_view.PILOT["lat"], planter_view.PILOT["lng"], default_ref,
                                   planter_view.SIZES["small"])
default_plot_taken = Chain(settings).is_nullifier_active(default_plot.nullifier)
default_plot_status = ("This plot already has a tree registered on it." if default_plot_taken
                       else "This plot is free.")
print(f"planter default plot: pilot cell, reference {default_ref} active={default_plot_taken} -> "
      f"expect '{default_plot_status}' before GPS")
JARGON = ("spatialNullifier", "keccak", "eth_call", "VERIFIER_ROLE", "H3 res", "NullifierInUse", "tbaAddress",
          "mintTree", "initialDBH", "initialBiomass", "would revert")
TEXT_JS = "want => document.body.innerText.includes(want)"
HERO = "Every tree measured,"
CTA_REGISTER = "Register a tree"
CTA_PROTOCOL = "See the live on-chain assets"
HOME_EXPECT = [HERO, "Verifiable climate action, on Celo", "Why this runs on Celo",
               "Built for the phone in the planter's hand", "A ledger that does not undo the tree",
               "Cheap enough to charge per tree", "How a tree gets registered", "Trees registered",
               f"Celo · {settings.chain_id}", planter_view.short_hex(Web3.to_checksum_address(settings.proxy.address), 4, 5),
               " CELO"]
# Every element whose own text is painted in the lime; in light mode the list must be empty.
LIME_TEXT_JS = r"""() => Array.from(document.querySelectorAll('body *')).filter(e =>
    getComputedStyle(e).color === 'rgb(53, 208, 127)'
    && Array.from(e.childNodes).some(n => n.nodeType === 3 && n.textContent.trim()))
  .map(e => e.tagName + ':' + e.textContent.trim().slice(0, 40)).slice(0, 5)"""


def header_and_icon(page) -> list[str]:
    missing = []
    header = page.evaluate("""() => { const bar = document.querySelector('.br-appbar');
        return bar ? [!!bar.querySelector('svg[aria-label^="BioRig brandmark"]'), bar.innerText] : null; }""")
    if not header or not header[0] or "BioRig" not in header[1] or settings.chain_name not in header[1]:
        missing.append(f"branded header with mark, wordmark and '{settings.chain_name}' chip: got {header}")
    icon = page.evaluate("""async () => { const l = document.querySelector('link[rel~="icon"]');
        if (!l) return null; const r = await fetch(l.href); return [l.href, r.status, r.headers.get('content-type')]; }""")
    if not icon or icon[1] != 200 or "image/png" not in (icon[2] or "") or "favicon.ico" in icon[0]:
        missing.append(f"brand favicon served as PNG: got {icon}")
    return missing


def lime_text(page, scheme: str) -> list[str]:
    if scheme != "light":
        return []
    return [f"lime text in light mode: {hit}" for hit in page.evaluate(LIME_TEXT_JS)]


def open_home(page) -> bool:
    page.goto(url)
    try:
        page.wait_for_function(TEXT_JS, arg=HERO, timeout=90_000)
        return True
    except PlaywrightTimeout:
        return False


def home_pass(page, scheme: str) -> list[str]:
    """The first screen: hero, both calls to action, the Celo cards, the live strip, no protocol terms."""
    if not open_home(page):
        return [HERO]
    missing = []
    try:
        page.wait_for_function("want => want.every(e => document.body.textContent.includes(e))", arg=HOME_EXPECT,
                               timeout=60_000)
    except PlaywrightTimeout:
        pass
    # textContent, not innerText: the section labels are uppercased by CSS, and the check reads the words.
    missing += [e for e in HOME_EXPECT if e not in page.evaluate("document.body.textContent")]
    body = page.evaluate("document.body.innerText")
    for name in (CTA_REGISTER, CTA_PROTOCOL):
        if not page.get_by_role("button", name=name).is_visible():
            missing.append(f"call to action: {name}")
    missing += header_and_icon(page)
    missing += [f"jargon on home: {j}" for j in JARGON if j in body]
    missing += lime_text(page, scheme)
    return missing


def enter(page, cta: str) -> bool:
    """From a fresh home screen, press one of its calls to action."""
    if not open_home(page):
        return False
    page.get_by_role("button", name=cta).click()
    return True


def planter_pass(page, scheme: str) -> list[str]:
    """Enter from home, walk the three steps; return what was missing or wrong."""
    missing = []
    if not enter(page, CTA_REGISTER):
        return [f"home, to press '{CTA_REGISTER}'"]

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
    missing += header_and_icon(page)
    for text in ("208", "359", "Chave et al. 2014"):
        wait_text(text, 10_000)
    missing += lime_text(page, scheme)
    page.get_by_role("button", name="Continue →").click()
    if not wait_text("Where is the tree?"):
        return missing
    wait_text("The pilot plot (Nairobi)", 30_000)
    wait_text(planter_view.short_hex(default_plot.nullifier_hex, 6, 4), 30_000)  # the default plot's ID
    wait_text(default_plot_status, 30_000)
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
    if NO_KEY:
        if not page.get_by_role("button", name="Check this tree →").is_disabled():
            missing.append("read-only: 'Check this tree' should be disabled with no signer")
        if not wait_text(READ_ONLY_PLANTER):
            missing.append(f"read-only notice: {READ_ONLY_PLANTER}")
        return missing
    page.get_by_role("button", name="Check this tree →").click()
    wait_text(planter_verdict, 120_000)
    body = page.evaluate("document.body.innerText")
    if ("Ready." in body) == ("Not this one." in body):
        missing.append("exactly one pre-flight verdict")
    missing += [f"jargon on the planter flow: {j}" for j in JARGON if j in body]
    missing += lime_text(page, scheme)
    return missing


def wait_verdict(page, want: str, nullifier_hex: str) -> bool:
    try:
        page.wait_for_function(VERDICT_JS, arg=[want, nullifier_hex], timeout=120_000)
        return True
    except PlaywrightTimeout:
        return False

failures = []
renders = 0
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
            h_missing = home_pass(page, scheme)
            h_overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
            h_mode = page.evaluate("document.documentElement.getAttribute('data-app-mode')")
            h_status = "ok"
            if h_missing or errors or h_mode != scheme or h_overflow:
                h_status = "FAIL"
                failures.append(("home", scheme, width, h_missing, errors[:3], h_mode, h_overflow))
            print(f"  home     {scheme:5} {width:4}px  mode={h_mode}  missing={h_missing}  "
                  f"console_errors={len(errors)}  h-overflow={h_overflow}  {h_status}")
            renders += 1
            p_missing = planter_pass(page, scheme)
            p_overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
            p_mode = page.evaluate("document.documentElement.getAttribute('data-app-mode')")
            p_status = "ok"
            if p_missing or errors or p_mode != scheme or p_overflow:
                p_status = "FAIL"
                failures.append(("planter", scheme, width, p_missing, errors[:3], p_mode, p_overflow))
            print(f"  planter  {scheme:5} {width:4}px  mode={p_mode}  missing={p_missing}  "
                  f"console_errors={len(errors)}  h-overflow={p_overflow}  {p_status}")
            renders += 1
            entered = enter(page, CTA_PROTOCOL)
            # The panels fill in independently (getTreeStats can land after the TBA check on a slow RPC), so wait for
            # every expected string; whatever is still absent at the timeout is reported as missing below.
            try:
                page.wait_for_function("want => want.every(e => document.body.innerText.includes(e))", arg=expect,
                                       timeout=120_000)
            except PlaywrightTimeout:
                pass
            body = page.evaluate("document.body.innerText")
            # On a cold app a panel can land (or re-render mid-rerun) just after that snapshot, so give whatever is
            # still absent a fresh window of its own before judging; a string that never appears is still reported.
            late = [e for e in expect if e not in body]
            if late:
                try:
                    page.wait_for_function("want => want.every(e => document.body.innerText.includes(e))", arg=late,
                                           timeout=120_000)
                except PlaywrightTimeout:
                    pass
                body = page.evaluate("document.body.innerText")
            missing = [e for e in expect if e not in body]
            if not entered:
                missing.append(f"home, to press '{CTA_PROTOCOL}'")
            missing += lime_text(page, scheme)
            if NO_KEY:
                pass  # no signer, no simulation: the read-only notice is in `expect`
            elif not wait_verdict(page, default_want, default.nullifier_hex):
                missing.append(f"default form: would {default_want}")
            # A new tree in the same cell: type a fresh salt and commit it with Enter, which is when Streamlit reruns.
            try:
                salt_box = page.get_by_label("salt", exact=True)
                salt_box.fill(fresh_salt, timeout=30_000)
                salt_box.press("Enter")
                fresh_ok = NO_KEY or wait_verdict(page, "succeed", fresh.nullifier_hex)
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
            renders += 1
            context.close()
    # The published links: ?view=planter and ?view=operator are aliases now, and must still open the same screens.
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    for value, marker in (("planter", "How thick is the trunk?"), ("operator", "spatialNullifier")):
        page.goto(url.rstrip("/") + f"/?view={value}")
        try:
            page.wait_for_function(TEXT_JS, arg=marker, timeout=90_000)
            alias_ok = HERO not in page.evaluate("document.body.innerText")
        except PlaywrightTimeout:
            alias_ok = False
        print(f"  alias    ?view={value:8} -> '{marker}'  {'ok' if alias_ok else 'FAIL'}")
        if not alias_ok:
            failures.append(("alias", value, marker))
    context.close()
    browser.close()
print(f"{renders} renders")
if renders != 12:
    failures.append(("renders", renders))
if failures:
    print("UI CHECK FAILED", failures)
    sys.exit(1)
print("UI CHECK OK")
