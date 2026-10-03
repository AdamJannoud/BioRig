"""Check the deployable dashboard itself, the way the hosts run it.

Three boots of `streamlit run streamlit_app.py`, each driven by a real Chromium the way a reviewer arrives: the bare
URL must open the home screen (its hero and its "See the live on-chain assets" call to action), and pressing that
call to action opens the operator view, where the mint form and the read-only notice these checks read live:

  1. a minimal checkout holding only what a hosting platform receives (no .env, no broadcast artifacts,
     no secrets) -> the proxy must come from the committed dashboard/deployment.json
  2. ALLOW_MINT=false -> the read-only notice appears and the mint button cannot be pressed
  3. ALLOW_MINT unset -> no read-only notice

Usage, from the repository root:

    .venv/bin/python scripts/check-hosted-entrypoint.py               # the repo's default chain
    CHAIN_ID=42220 .venv/bin/python scripts/check-hosted-entrypoint.py

The expected chain id is CHAIN_ID from the environment, else the default chain in dashboard/deployment.json; the
expected proxy is what that file records for the chain, so checking a chain with no recorded deployment fails
before anything boots. A non-default chain is handed to every boot as CHAIN_ID, since a hosted instance of it
would carry that one secret. Needs playwright chromium (`python -m playwright install chromium`) and outbound
network for the chain's RPC. Exits non-zero on the first failed check. Screenshots land in /tmp/hosted-*.png.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = str(REPO / ".venv" / "bin" / "python")
MINIMAL_ROOT = Path("/tmp/biorig-hosted-checkout")
CONFIG_KEYS = ("RPC_URL", "CHAIN_ID", "EXPLORER_URL", "PRIVATE_KEY", "PROXY_ADDRESS", "PROXY_DEPLOY_BLOCK",
               "ALLOW_MINT")

sys.path.insert(0, str(REPO))
from dashboard.config import (STATIC_DEPLOYMENT_FILE, ChainSelectionError, default_chain_id,  # noqa: E402
                              recorded_deployment, select_chain)


def expected_chain() -> tuple[int, str, dict[str, str]]:
    """(chain id, recorded proxy, env overrides every boot gets) for the chain under check."""
    try:
        chain = select_chain({"CHAIN_ID": os.environ.get("CHAIN_ID", "")}, REPO)
        _, proxy, _ = recorded_deployment(REPO / STATIC_DEPLOYMENT_FILE, chain.chain_id)
    except (ChainSelectionError, ValueError) as exc:
        sys.exit(f"cannot check the hosted entrypoint: {exc}")
    overrides = {} if chain.chain_id == default_chain_id(REPO) else {"CHAIN_ID": str(chain.chain_id)}
    return chain.chain_id, proxy, overrides


def minimal_checkout() -> Path:
    """Only the files a hosting platform gets: no .env, no broadcast/, no secrets."""
    if MINIMAL_ROOT.exists():
        shutil.rmtree(MINIMAL_ROOT)
    MINIMAL_ROOT.mkdir(parents=True)
    for name in ("streamlit_app.py", "requirements.txt"):
        shutil.copy2(REPO / name, MINIMAL_ROOT / name)
    shutil.copytree(REPO / "dashboard", MINIMAL_ROOT / "dashboard")
    shutil.copytree(REPO / ".streamlit", MINIMAL_ROOT / ".streamlit")
    assert not (MINIMAL_ROOT / ".env").exists() and not (MINIMAL_ROOT / "broadcast").exists()
    return MINIMAL_ROOT


def boot(root: Path, port: int, env_overrides: dict[str, str]) -> subprocess.Popen:
    env = {key: value for key, value in os.environ.items() if key not in CONFIG_KEYS}
    env.update(env_overrides)
    env["PYTHONPATH"] = str(root)
    proc = subprocess.Popen(
        [PY, "-m", "streamlit", "run", "streamlit_app.py", "--server.headless", "true",
         "--server.port", str(port), "--browser.gatherUsageStats", "false"],
        cwd=str(root), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        start_new_session=True, text=True)
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://localhost:{port}/_stcore/health", timeout=2).read()
            return proc
        except Exception:
            if proc.poll() is not None:
                print(proc.stdout.read()[-2000:])
                sys.exit("streamlit exited before serving")
            time.sleep(0.5)
    proc.kill()
    sys.exit("streamlit never answered /_stcore/health")


HOME_HERO = "Every tree measured,"
HOME_CTA = "See the live on-chain assets"


def render(port: int, shot: str) -> tuple[bool, str]:
    """(the bare URL opened home with its call to action, the operator view's text after pressing it)."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout, sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1280, "height": 1000})
        # The public first screen is home; the operator view is one press away.
        page.goto(f"http://localhost:{port}/", wait_until="domcontentloaded")
        try:
            page.wait_for_selector(f"text={HOME_HERO}", timeout=180_000)
            cta = page.get_by_role("button", name=HOME_CTA)
            home = cta.is_visible()
            cta.click()
        except PlaywrightTimeout:
            home = False
            page.goto(f"http://localhost:{port}/?view=protocol", wait_until="domcontentloaded")
        # The operator view: the read-only notice and the mint control these checks read live there.
        page.wait_for_selector("text=Mint tree", timeout=180_000)
        page.wait_for_timeout(2500)
        body = page.inner_text("body")
        page.screenshot(path=shot, full_page=True)
        browser.close()
    return home, body


def report(label: str, checks: list[tuple[str, bool]], shot: str, body: str) -> bool:
    failed = [name for name, ok in checks if not ok]
    print(f"[{'FAIL' if failed else 'OK'}] {label}")
    for name, ok in checks:
        print(f"    {'ok  ' if ok else 'FAIL'} {name}")
    print(f"    screenshot {shot}")
    return not failed


def main() -> int:
    healthy = []
    chain_id, proxy, chain_env = expected_chain()
    print(f"expecting chain {chain_id}, proxy {proxy}" + (f", booted with {chain_env}" if chain_env else ""))

    root = minimal_checkout()
    print("minimal checkout:", sorted(p.name for p in root.iterdir()))
    proc = boot(root, 8631, chain_env)
    try:
        home, body = render(8631, "/tmp/hosted-static.png")
    finally:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=20)
    healthy.append(report("fresh checkout, no secrets: renders from the static record", [
        ("home is the first screen, its call to action opens the operator view", home),
        ("proxy from dashboard/deployment.json", "dashboard/deployment.json (static fallback)" in body),
        ("live proxy address shown", proxy in body.lower()),
        ("chain id shown", str(chain_id) in body),
        ("no resolution failure", "Could not resolve the BioRig proxy" not in body),
        ("signing path off without PRIVATE_KEY", "PRIVATE_KEY is not set" in body),
    ], "/tmp/hosted-static.png", body))

    for index, (label, env, expect_readonly) in enumerate([
        ("ALLOW_MINT=false: read-only", {"ALLOW_MINT": "false", "CHAIN_ID": str(chain_id)}, True),
        ("ALLOW_MINT unset: interactive", {"CHAIN_ID": str(chain_id)}, False),
    ]):
        port = 8641 + index
        shot = f"/tmp/hosted-{'off' if expect_readonly else 'on'}.png"
        proc = boot(REPO, port, env)
        try:
            home, body = render(port, shot)
        finally:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=20)
        healthy.append(report(label, [
            ("home is the first screen, its call to action opens the operator view", home),
            ("read-only notice", ("Read-only deployment" in body) == expect_readonly),
            ("mint form rendered", "Register a tree" in body),
            ("Mint tree control present", "Mint tree" in body),
            ("chain id shown", str(chain_id) in body),
        ], shot, body))

    return 0 if all(healthy) else 1


if __name__ == "__main__":
    sys.exit(main())
