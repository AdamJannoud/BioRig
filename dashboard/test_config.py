import json
import subprocess
import sys
from pathlib import Path

import pytest

from dashboard import config
from dashboard.config import (CONFIG_KEYS, ChainSelectionError, ProxyResolutionError, Settings, chain_config,
                              load_dotenv, load_settings, record_deployment, resolve_proxy, select_chain)

SEPOLIA, MAINNET = 11142220, 42220
LIVE_PROXY = "0x21ab8b36177f65ce69e04e281e4aff3db6b5f7e6"  # the real Celo Sepolia deployment
IMPL = "0x4c998c6553c78bb9d5a67aac6fbc526d64dba3a4"
REPO = Path(__file__).resolve().parent.parent
REGISTRY = "0x000000006551c19487814612e58fe06813775758"
REGISTRY_CODEHASH = "0xda1d5b06e579f9e42e59b00fbc22939896ecb38dc8830d40de0a2508fecd6735"

# What each chain must resolve to, written out rather than read from chains.json, so the registry is under test.
# The mainnet proxy is synthetic: nothing is deployed on 42220, and no fixture may pretend otherwise.
EXPECTED = {
    SEPOLIA: dict(name="Celo Sepolia", testnet=True, rpc_url="https://forno.celo-sepolia.celo-testnet.org",
                  explorer_url="https://celo-sepolia.blockscout.com",
                  verifier_url="https://celo-sepolia.blockscout.com/api/",
                  faucet_url="https://faucet.celo.org/celo-sepolia", proxy=LIVE_PROXY),
    MAINNET: dict(name="Celo mainnet", testnet=False, rpc_url="https://forno.celo.org",
                  explorer_url="https://celo.blockscout.com", verifier_url="https://celo.blockscout.com/api/",
                  faucet_url=None, proxy="0x" + "a2" * 20),
}


def _other(chain_id: int) -> int:
    return MAINNET if chain_id == SEPOLIA else SEPOLIA


def _broadcast(root: Path, script: str, payload, chain_id: int) -> Path:
    path = root / "broadcast" / script / str(chain_id) / "run-latest.json"
    path.parent.mkdir(parents=True)
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload))
    return path


def _run(proxy, chain_id: int):
    return {
        "chain": chain_id,
        "transactions": [
            {"transactionType": "CREATE", "contractName": "BioRigCoreV5", "contractAddress": IMPL, "hash": "0x01"},
            {"transactionType": "CREATE", "contractName": "ERC1967Proxy", "contractAddress": proxy, "hash": "0x02"},
            {"transactionType": "CALL", "contractName": "ERC1967Proxy", "contractAddress": proxy, "hash": "0x03"},
        ],
        "receipts": [{"transactionHash": h, "blockNumber": "0x23c65b4", "status": "0x1"}
                     for h in ("0x01", "0x02", "0x03")],
    }


def _deployment_file(root: Path, payload: dict) -> Path:
    (root / "dashboard").mkdir(exist_ok=True)
    path = root / "dashboard" / "deployment.json"
    path.write_text(json.dumps(payload))
    return path


@pytest.fixture(autouse=True)
def _clean_config_env(monkeypatch):
    """Keep the process environment out of every test here, so precedence is what is under test."""
    for key in CONFIG_KEYS:
        monkeypatch.delenv(key, raising=False)


# --------------------------------------------------------------------------- chain registry


def test_registry_holds_each_chains_own_values(chain_id):
    c, want = chain_config(chain_id), EXPECTED[chain_id]
    assert c.chain_id == chain_id
    assert (c.name, c.testnet, c.rpc_url, c.explorer_url, c.verifier_url, c.faucet_url) == (
        want["name"], want["testnet"], want["rpc_url"], want["explorer_url"], want["verifier_url"],
        want["faucet_url"])
    assert c.native_currency == "CELO"
    assert c.erc6551_registry == REGISTRY and c.erc6551_registry_codehash == REGISTRY_CODEHASH


def test_explicit_chain_id_selects_that_chain(chain_id, tmp_path):
    _deployment_file(tmp_path, {"default_chain_id": _other(chain_id), "deployments": {}})
    assert select_chain({"CHAIN_ID": str(chain_id)}, tmp_path).chain_id == chain_id


def test_default_chain_comes_from_deployment_json(chain_id, tmp_path):
    _deployment_file(tmp_path, {"default_chain_id": chain_id, "deployments": {}})
    assert select_chain({}, tmp_path).name == EXPECTED[chain_id]["name"]
    _deployment_file(tmp_path, {"chain_id": chain_id, "proxy_address": EXPECTED[chain_id]["proxy"]})  # flat
    assert select_chain({}, tmp_path).chain_id == chain_id


def test_no_chain_selected_fails_loudly_with_the_candidates(tmp_path):
    with pytest.raises(ChainSelectionError) as exc:
        select_chain({}, tmp_path)
    msg = str(exc.value)
    assert "CHAIN_ID is not set" in msg and "file not found" in msg
    assert "42220 (Celo mainnet)" in msg and "11142220 (Celo Sepolia)" in msg


def test_unknown_or_malformed_chain_id_fails_loudly(tmp_path):
    with pytest.raises(ChainSelectionError, match=r"chain 5 is not in dashboard/chains.json; known chains: 42220"):
        select_chain({"CHAIN_ID": "5"}, tmp_path)
    with pytest.raises(ChainSelectionError, match="'0xa4ec' is not an integer"):
        select_chain({"CHAIN_ID": "0xa4ec"}, tmp_path)


def test_derived_module_defaults_follow_the_committed_default_chain():
    default = json.loads((REPO / "dashboard" / "deployment.json").read_text())["default_chain_id"]
    assert config.EXPECTED_CHAIN_ID == default
    assert config.DEFAULT_RPC_URL == EXPECTED[default]["rpc_url"]
    assert config.DEFAULT_EXPLORER_URL == EXPECTED[default]["explorer_url"]


def test_malformed_registry_fails_loudly(tmp_path):
    bad = tmp_path / "chains.json"
    bad.write_text(json.dumps({"chains": {"42220": {"name": "Celo mainnet"}}}))
    with pytest.raises(ChainSelectionError, match="chain '42220' is missing testnet, native_currency, rpc_url"):
        config.load_chains(bad)


# --------------------------------------------------------------------------- proxy resolution


def test_deployall_broadcast_wins_over_env(chain_id, tmp_path):
    proxy = EXPECTED[chain_id]["proxy"]
    _broadcast(tmp_path, "DeployAll.s.sol", _run(proxy, chain_id), chain_id)
    r = resolve_proxy(tmp_path, {"PROXY_ADDRESS": "0x" + "11" * 20, "CHAIN_ID": str(chain_id)})
    assert r.address == proxy  # the proxy, not the implementation
    assert r.source == f"broadcast/DeployAll.s.sol/{chain_id}/run-latest.json"
    assert r.deploy_block == 0x23C65B4
    assert r.skipped == ()


def test_broadcast_for_the_other_chain_is_not_used(chain_id, tmp_path):
    _broadcast(tmp_path, "DeployAll.s.sol", _run("0x" + "cc" * 20, _other(chain_id)), _other(chain_id))
    r = resolve_proxy(tmp_path, {"PROXY_ADDRESS": EXPECTED[chain_id]["proxy"]}, chain_id)
    assert r.address == EXPECTED[chain_id]["proxy"] and r.source == ".env PROXY_ADDRESS"
    assert r.skipped[0] == f"broadcast/DeployAll.s.sol/{chain_id}/run-latest.json: file not found"


def test_deploybiorig_broadcast_is_second(chain_id, tmp_path):
    other = "0x" + "ab" * 20
    _broadcast(tmp_path, "DeployBioRig.s.sol", _run(other, chain_id), chain_id)
    r = resolve_proxy(tmp_path, {"PROXY_ADDRESS": "0x" + "11" * 20}, chain_id)
    assert r.address == other
    assert r.source == f"broadcast/DeployBioRig.s.sol/{chain_id}/run-latest.json"
    assert "DeployAll.s.sol" in r.skipped[0] and "not found" in r.skipped[0]


def test_env_fallback_when_no_broadcast(chain_id, tmp_path):
    proxy = EXPECTED[chain_id]["proxy"]
    r = resolve_proxy(tmp_path, {"PROXY_ADDRESS": proxy.upper().replace("0X", "0x"), "PROXY_DEPLOY_BLOCK": "123"},
                      chain_id)
    assert r.address == proxy
    assert r.source == ".env PROXY_ADDRESS"
    assert r.deploy_block == 123
    assert r.skipped == (f"broadcast/DeployAll.s.sol/{chain_id}/run-latest.json: file not found",
                         f"broadcast/DeployBioRig.s.sol/{chain_id}/run-latest.json: file not found")


def test_malformed_broadcast_falls_through_with_reason(chain_id, tmp_path):
    _broadcast(tmp_path, "DeployAll.s.sol", "{not json", chain_id)
    r = resolve_proxy(tmp_path, {"PROXY_ADDRESS": EXPECTED[chain_id]["proxy"]}, chain_id)
    assert r.source == ".env PROXY_ADDRESS"
    assert "malformed JSON" in r.skipped[0]


def test_broadcast_without_proxy_is_skipped(chain_id, tmp_path):
    run = _run(EXPECTED[chain_id]["proxy"], chain_id)
    run["transactions"] = run["transactions"][:1]
    _broadcast(tmp_path, "DeployAll.s.sol", run, chain_id)
    with pytest.raises(ProxyResolutionError) as exc:
        resolve_proxy(tmp_path, {}, chain_id)
    msg = str(exc.value)
    assert "no ERC1967Proxy creation" in msg
    assert "PROXY_ADDRESS: not set" in msg
    assert "add PROXY_ADDRESS" in msg


def test_invalid_env_address_fails_loudly(chain_id, tmp_path):
    with pytest.raises(ProxyResolutionError, match="not a 20-byte hex address"):
        resolve_proxy(tmp_path, {"PROXY_ADDRESS": "0x1234"}, chain_id)


def test_bad_contract_address_in_broadcast(chain_id, tmp_path):
    _broadcast(tmp_path, "DeployAll.s.sol", _run("0xnothex", chain_id), chain_id)
    with pytest.raises(ProxyResolutionError, match="invalid contractAddress"):
        resolve_proxy(tmp_path, {}, chain_id)


def test_resolve_proxy_selects_the_chain_from_env_when_not_given(chain_id, tmp_path):
    _broadcast(tmp_path, "DeployAll.s.sol", _run(EXPECTED[chain_id]["proxy"], chain_id), chain_id)
    assert resolve_proxy(tmp_path, {"CHAIN_ID": str(chain_id)}).address == EXPECTED[chain_id]["proxy"]


def test_load_dotenv_parsing(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# c\nA=1\nexport B = two \nC=\"q v\"\nbad line\nA=3\n")
    assert load_dotenv(p) == {"A": "3", "B": "two", "C": "q v"}
    assert load_dotenv(tmp_path / "missing") == {}


def test_settings_repr_never_shows_key(chain_id, tmp_path):
    key = "0x" + "ab" * 32
    (tmp_path / ".env").write_text(f"PRIVATE_KEY={key}\nPROXY_ADDRESS={EXPECTED[chain_id]['proxy']}\n"
                                   f"CHAIN_ID={chain_id}\n")
    s = load_settings(tmp_path)
    assert s.private_key == key
    assert key not in repr(s) and key not in str(s) and "<set>" in repr(s)
    assert f"chain_id={chain_id}" in repr(s)


def test_settings_take_the_selected_chains_defaults(chain_id, tmp_path):
    want = EXPECTED[chain_id]
    (tmp_path / ".env").write_text(f"CHAIN_ID={chain_id}\nPROXY_ADDRESS={want['proxy']}\n")
    s = load_settings(tmp_path, secrets={})
    assert (s.chain_id, s.rpc_url, s.explorer_url, s.chain_name) == (
        chain_id, want["rpc_url"], want["explorer_url"], want["name"])
    assert s.chain == chain_config(chain_id)
    assert s.proxy.address == want["proxy"]


def test_real_repo_resolves_live_proxy():
    r = resolve_proxy(REPO, {}, SEPOLIA)
    assert r.address == LIVE_PROXY
    assert "DeployAll.s.sol" in r.source


def test_real_repo_resolves_mainnet_only_from_a_real_broadcast():
    """Until a Celo mainnet broadcast is committed, selecting mainnet must fail loudly rather than borrow Sepolia's
    proxy; once one is, it must resolve to exactly that broadcast's proxy."""
    broadcast = REPO / "broadcast" / "DeployAll.s.sol" / str(MAINNET) / "run-latest.json"
    if not broadcast.is_file():
        with pytest.raises(ProxyResolutionError) as exc:
            resolve_proxy(REPO, {}, MAINNET)
        msg = str(exc.value)
        assert "broadcast/DeployAll.s.sol/42220/run-latest.json: file not found" in msg
        assert "dashboard/deployment.json: no deployment recorded for chain 42220 (recorded: 11142220)" in msg
    else:
        r = resolve_proxy(REPO, {}, MAINNET)
        assert r.source == "broadcast/DeployAll.s.sol/42220/run-latest.json"
        assert r.address == config._proxy_from_broadcast(broadcast)[0]


# --------------------------------------------------------------------------- hosted deployment


def test_static_deployment_is_the_last_resort(chain_id, tmp_path):
    proxy = EXPECTED[chain_id]["proxy"]
    _deployment_file(tmp_path, {"default_chain_id": chain_id, "deployments": {
        str(chain_id): {"proxy_address": proxy.upper().replace("0X", "0x"), "proxy_deploy_block": 37511856}}})
    r = resolve_proxy(tmp_path, {"PROXY_ADDRESS": ""})
    assert r.address == proxy
    assert r.source == "dashboard/deployment.json (static fallback)"
    assert r.deploy_block == 37511856
    assert len(r.skipped) == 3  # both broadcasts, then the empty env var


def test_legacy_flat_static_record_still_resolves(chain_id, tmp_path):
    proxy = EXPECTED[chain_id]["proxy"]
    _deployment_file(tmp_path, {"chain_id": chain_id, "proxy_address": proxy, "proxy_deploy_block": 7})
    s = load_settings(tmp_path, secrets={})
    assert (s.chain_id, s.proxy.address, s.proxy.deploy_block) == (chain_id, proxy, 7)
    assert s.proxy.source == "dashboard/deployment.json (static fallback)"


def test_multi_chain_static_record_resolves_each_chain_to_its_own_entry(tmp_path):
    _deployment_file(tmp_path, {"default_chain_id": SEPOLIA, "deployments": {
        str(SEPOLIA): {"proxy_address": EXPECTED[SEPOLIA]["proxy"], "proxy_deploy_block": 37511856},
        str(MAINNET): {"proxy_address": EXPECTED[MAINNET]["proxy"], "proxy_deploy_block": 40000001}}})
    sep, main = resolve_proxy(tmp_path, {}, SEPOLIA), resolve_proxy(tmp_path, {}, MAINNET)
    assert (sep.address, sep.deploy_block) == (EXPECTED[SEPOLIA]["proxy"], 37511856)
    assert (main.address, main.deploy_block) == (EXPECTED[MAINNET]["proxy"], 40000001)
    assert load_settings(tmp_path, secrets={"CHAIN_ID": str(MAINNET)}).proxy.address == EXPECTED[MAINNET]["proxy"]
    assert load_settings(tmp_path, secrets={}).chain_id == SEPOLIA  # the default, absent CHAIN_ID


def test_static_deployment_never_beats_a_configured_address(chain_id, tmp_path):
    _deployment_file(tmp_path, {"default_chain_id": chain_id, "deployments": {
        str(chain_id): {"proxy_address": "0x" + "ab" * 20}}})
    r = resolve_proxy(tmp_path, {"PROXY_ADDRESS": EXPECTED[chain_id]["proxy"]})
    assert r.address == EXPECTED[chain_id]["proxy"] and r.source == ".env PROXY_ADDRESS"


def test_static_deployment_for_another_chain_is_refused(chain_id, tmp_path):
    other = _other(chain_id)
    _deployment_file(tmp_path, {"default_chain_id": other, "deployments": {
        str(other): {"proxy_address": EXPECTED[other]["proxy"]}}})
    with pytest.raises(ProxyResolutionError, match=f"no deployment recorded for chain {chain_id} "
                                                   fr"\(recorded: {other}\)"):
        resolve_proxy(tmp_path, {}, chain_id)
    _deployment_file(tmp_path, {"chain_id": other, "proxy_address": EXPECTED[other]["proxy"]})  # flat
    with pytest.raises(ProxyResolutionError, match=f"records chain {other}, not {chain_id}"):
        resolve_proxy(tmp_path, {}, chain_id)


def test_committed_deployment_json_matches_the_live_broadcast():
    """The static record must agree with the broadcast that actually deployed it, or the fallback lies."""
    from dashboard.config import _proxy_from_deployment

    addr, block = _proxy_from_deployment(REPO / "dashboard" / "deployment.json", SEPOLIA)
    assert addr == LIVE_PROXY and block == 37511856
    broadcast = json.loads((REPO / "broadcast" / "DeployAll.s.sol" / str(SEPOLIA) / "run-latest.json").read_text())
    proxy_tx = [t for t in broadcast["transactions"]
                if t.get("contractName") == "ERC1967Proxy"
                and t.get("transactionType") in ("CREATE", "CREATE2")][-1]
    assert proxy_tx["contractAddress"].lower() == addr


def test_committed_deployment_json_records_a_chain_exactly_when_its_broadcast_exists(chain_id):
    """No entry can be typed in by hand: a chain is recorded if and only if its DeployAll broadcast is committed, and
    then with that broadcast's proxy and block (scripts/record_deployment.py writes it from there)."""
    from dashboard.config import _proxy_from_broadcast, _proxy_from_deployment

    record = json.loads((REPO / "dashboard" / "deployment.json").read_text())
    assert record["default_chain_id"] in config.CHAINS and str(record["default_chain_id"]) in record["deployments"]
    broadcast = REPO / "broadcast" / "DeployAll.s.sol" / str(chain_id) / "run-latest.json"
    assert (str(chain_id) in record["deployments"]) == broadcast.is_file()
    if broadcast.is_file():
        path = REPO / "dashboard" / "deployment.json"
        assert _proxy_from_deployment(path, chain_id) == _proxy_from_broadcast(broadcast)


def test_hosted_secrets_reach_the_settings(chain_id, tmp_path):
    (tmp_path / ".env").write_text(f"PROXY_ADDRESS={EXPECTED[chain_id]['proxy']}\n")
    s = load_settings(tmp_path, secrets={"PRIVATE_KEY": "0x" + "cd" * 32, "ALLOW_MINT": "false",
                                         "RPC_URL": "https://rpc.example", "CHAIN_ID": str(chain_id)})
    assert s.private_key == "0x" + "cd" * 32
    assert s.allow_mint is False
    assert s.rpc_url == "https://rpc.example"
    assert s.chain_id == chain_id and s.explorer_url == EXPECTED[chain_id]["explorer_url"]
    assert "0x" + "cd" * 32 not in repr(s)


def test_secrets_beat_the_env_file_but_not_the_process_environment(chain_id, tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(f"PROXY_ADDRESS={EXPECTED[chain_id]['proxy']}\nRPC_URL=https://from-file\n"
                                   f"CHAIN_ID={_other(chain_id)}\n")
    s = load_settings(tmp_path, secrets={"RPC_URL": "https://from-secrets", "CHAIN_ID": str(chain_id)})
    assert (s.rpc_url, s.chain_id) == ("https://from-secrets", chain_id)
    monkeypatch.setenv("RPC_URL", "https://from-process")
    monkeypatch.setenv("CHAIN_ID", str(_other(chain_id)))
    s = load_settings(tmp_path, secrets={"RPC_URL": "https://from-secrets", "CHAIN_ID": str(chain_id)})
    assert (s.rpc_url, s.chain_id) == ("https://from-process", _other(chain_id))


def test_allow_mint_defaults_to_on_and_parses_off(chain_id, tmp_path):
    (tmp_path / ".env").write_text(f"PROXY_ADDRESS={EXPECTED[chain_id]['proxy']}\nCHAIN_ID={chain_id}\n")
    assert load_settings(tmp_path).allow_mint is True
    for value, expected in (("false", False), ("False", False), ("0", False), ("no", False), ("off", False),
                            ("true", True), ("1", True), ("yes", True), ("on", True), ("", True),
                            ("junk", False)):
        assert load_settings(tmp_path, secrets={"ALLOW_MINT": value}).allow_mint is expected, value


def test_hosted_secrets_are_empty_and_silent_without_a_secrets_file():
    from dashboard.config import hosted_secrets

    assert hosted_secrets() == {}


# --------------------------------------------------------------------------- recording a deployment


def test_record_deployment_adds_a_chain_without_touching_the_others(chain_id, tmp_path):
    other = _other(chain_id)
    path = _deployment_file(tmp_path, {"chain_id": other, "proxy_address": EXPECTED[other]["proxy"].upper()
                                       .replace("0X", "0x"), "proxy_deploy_block": 5})  # flat, migrated
    data = record_deployment(path, chain_id, EXPECTED[chain_id]["proxy"], 99)
    assert data == json.loads(path.read_text())
    assert data["default_chain_id"] == other
    assert data["deployments"][str(other)] == {"proxy_address": EXPECTED[other]["proxy"], "proxy_deploy_block": 5}
    assert data["deployments"][str(chain_id)] == {"proxy_address": EXPECTED[chain_id]["proxy"],
                                                  "proxy_deploy_block": 99}
    assert resolve_proxy(tmp_path, {}, chain_id).address == EXPECTED[chain_id]["proxy"]
    assert record_deployment(path, chain_id, EXPECTED[chain_id]["proxy"], 99, make_default=True)[
        "default_chain_id"] == chain_id
    assert select_chain({}, tmp_path).chain_id == chain_id


def test_record_deployment_refuses_overwrite_unknown_chain_and_bad_address(tmp_path):
    path = _deployment_file(tmp_path, {"default_chain_id": SEPOLIA, "deployments": {
        str(SEPOLIA): {"proxy_address": LIVE_PROXY, "proxy_deploy_block": 1}}})
    with pytest.raises(ValueError, match="already records proxy 0x21ab"):
        record_deployment(path, SEPOLIA, "0x" + "ab" * 20, 2)
    assert record_deployment(path, SEPOLIA, "0x" + "ab" * 20, 2, replace=True)["deployments"][str(SEPOLIA)][
        "proxy_address"] == "0x" + "ab" * 20
    with pytest.raises(ChainSelectionError, match="chain 5 is not in"):
        record_deployment(path, 5, LIVE_PROXY, 1)
    with pytest.raises(ValueError, match="not a 20-byte hex address"):
        record_deployment(path, MAINNET, "0x1234", 1)


def _record_cli(tmp_path, *args):
    return subprocess.run([sys.executable, str(REPO / "scripts" / "record_deployment.py"), "--no-rpc",
                           "--deployment-file", str(tmp_path / "deployment.json"), *args],
                          capture_output=True, text=True, cwd=REPO,
                          env={"PATH": "/usr/bin:/bin", "CHAIN_ID": "", "HOME": str(tmp_path)})


def test_record_cli_takes_the_proxy_from_a_confirmed_broadcast(chain_id, tmp_path):
    (tmp_path / "deployment.json").write_text(json.dumps({"default_chain_id": SEPOLIA, "deployments": {
        str(SEPOLIA): {"proxy_address": LIVE_PROXY, "proxy_deploy_block": 37511856}}}))
    artifact = tmp_path / "run-latest.json"
    run = _run(EXPECTED[chain_id]["proxy"], chain_id)
    run["transactions"].insert(0, {"transactionType": "CREATE", "contractName": "ERC6551Account",
                                   "contractAddress": "0x" + "3d" * 20, "hash": "0x00"})  # no CREATE2, as on mainnet
    run["receipts"].append({"transactionHash": "0x00", "blockNumber": "0x1", "status": "0x1"})
    artifact.write_text(json.dumps(run))
    out = _record_cli(tmp_path, "--chain-id", str(chain_id), "--broadcast", str(artifact), "--replace")
    assert out.returncode == 0, out.stderr
    data = json.loads((tmp_path / "deployment.json").read_text())
    assert data["deployments"][str(chain_id)] == {"proxy_address": EXPECTED[chain_id]["proxy"],
                                                  "proxy_deploy_block": 0x23C65B4}
    assert data["default_chain_id"] == SEPOLIA


def test_record_cli_refuses_a_simulation_and_the_wrong_chain(tmp_path):
    artifact = tmp_path / "run-latest.json"
    run = _run(EXPECTED[MAINNET]["proxy"], MAINNET)
    artifact.write_text(json.dumps(run))
    wrong = _record_cli(tmp_path, "--chain-id", str(SEPOLIA), "--broadcast", str(artifact))
    assert wrong.returncode == 1 and "is for chain 42220, not 11142220" in wrong.stderr
    run["receipts"] = []
    artifact.write_text(json.dumps(run))
    sim = _record_cli(tmp_path, "--chain-id", str(MAINNET), "--broadcast", str(artifact))
    assert sim.returncode == 1 and "has no receipt: this artifact is a simulation" in sim.stderr
    assert not (tmp_path / "deployment.json").exists()


def test_env_example_network_block_is_the_registry_entry_for_its_chain():
    """.env.example's network values must be exactly what `python3 -m dashboard.config env` prints for its CHAIN_ID,
    so the template cannot drift from dashboard/chains.json."""
    example = load_dotenv(REPO / ".env.example")
    c = chain_config(int(example["CHAIN_ID"]))
    assert (example["RPC_URL"], example["VERIFIER_URL"], example["EXPLORER_URL"]) == (
        c.rpc_url, c.verifier_url, c.explorer_url)
    out = subprocess.run([sys.executable, "-m", "dashboard.config", "env", "--chain-id", example["CHAIN_ID"]],
                         capture_output=True, text=True, cwd=REPO, check=True).stdout
    assert {k: v for k, v in load_dotenv_text(out).items()} == {
        "CHAIN_ID": example["CHAIN_ID"], "RPC_URL": c.rpc_url, "VERIFIER": "blockscout",
        "VERIFIER_URL": c.verifier_url, "EXPLORER_URL": c.explorer_url}


def load_dotenv_text(text: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in text.splitlines() if line and not line.startswith("#"))
