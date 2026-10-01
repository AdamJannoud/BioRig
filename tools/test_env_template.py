"""The `.env.mainnet` template must match the chain registry and cover every variable the deploy scripts require.

Two failures this pins down, both of which would otherwise land mid-runbook against mainnet: a variable a script
reads with no default but the template never mentions (`vm.envUint("X")` with no `X` set aborts the run), and a
network block that has drifted from `dashboard/chains.json`. The expected network values are read here from the
registry, not from the template, so the template cannot agree with itself.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from dashboard import config

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / ".env.mainnet.example"
LOCAL_FILE = REPO_ROOT / ".env.mainnet"
SCRIPT_DIR = REPO_ROOT / "script"

MAINNET = 42220

# `vm.envUint("X")` and friends: reads with no default, so the variable must be set. `vm.envOr("X", ...)` is
# deliberately excluded — a variable with a fallback is optional, which is how ERC6551_REGISTRY_MODE is omitted.
REQUIRED_READ = re.compile(r'vm\.env(?:Uint|Address|String|Bool|Bytes32|Bytes)\(\s*"([A-Za-z0-9_]+)"')
ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")

# What the runbook fills in by hand, so all of these must ship empty.
FILLED_BY_HAND = {"PRIVATE_KEY", "ADMIN", "BUFFER_POOL", "NEW_ADMIN", "VERIFIER_ADDRESS"}


def parse_template() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in TEMPLATE.read_text().splitlines():
        match = ENV_LINE.match(line)
        if match:
            values[match.group(1)] = match.group(2).strip()
    return values


def required_by_scripts() -> set[str]:
    names: set[str] = set()
    for path in sorted(SCRIPT_DIR.glob("*.sol")):
        names.update(REQUIRED_READ.findall(path.read_text()))
    return names


def test_template_exists_and_the_real_file_stays_ignored() -> None:
    assert TEMPLATE.is_file(), f"{TEMPLATE.name} is missing"
    if not (REPO_ROOT / ".git").is_dir():
        pytest.skip("not a git checkout")

    def is_ignored(path: Path) -> bool:
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", path.name],
            cwd=REPO_ROOT, capture_output=True, text=True)
        assert result.returncode in (0, 1), f"git check-ignore failed: {result.stderr}"
        return result.returncode == 0

    assert not is_ignored(TEMPLATE), f"{TEMPLATE.name} is gitignored, so the template would never reach the repo"
    assert is_ignored(LOCAL_FILE), f"{LOCAL_FILE.name} must stay gitignored: a deployer key goes in it"


def test_network_block_matches_the_chain_registry() -> None:
    chain = config.chain_config(MAINNET)
    values = parse_template()
    assert values["CHAIN_ID"] == str(chain.chain_id)
    assert values["RPC_URL"] == chain.rpc_url
    assert values["EXPLORER_URL"] == chain.explorer_url
    assert values["VERIFIER_URL"] == chain.verifier_url
    assert values["VERIFIER"] == "blockscout"
    assert values["ERC6551_REGISTRY"].lower() == chain.erc6551_registry


def test_every_variable_the_scripts_require_is_in_the_template() -> None:
    missing = sorted(required_by_scripts() - set(parse_template()))
    assert not missing, f"deploy scripts require these, but the template omits them: {missing}"


def test_the_key_and_role_addresses_ship_empty() -> None:
    values = parse_template()
    assert not values["PRIVATE_KEY"], "the template must never carry a value for PRIVATE_KEY"
    for name in sorted(FILLED_BY_HAND):
        assert values.get(name) == "", f"{name} must ship empty for the deployer to fill in"


def test_no_value_could_be_mistaken_for_key_material() -> None:
    for name, value in parse_template().items():
        if not value:
            continue
        assert not re.fullmatch(r"(?:0x)?[0-9a-fA-F]{64}", value), f"{name} looks like key material"
