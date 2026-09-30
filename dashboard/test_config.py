import json
from pathlib import Path

import pytest

from dashboard.config import (CONFIG_KEYS, ProxyResolutionError, Settings, load_dotenv, resolve_proxy,
                              load_settings)

CHAIN = 11142220
PROXY = "0x21ab8b36177f65ce69e04e281e4aff3db6b5f7e6"
IMPL = "0x4c998c6553c78bb9d5a67aac6fbc526d64dba3a4"
REPO = Path(__file__).resolve().parent.parent


def _broadcast(root: Path, script: str, payload) -> Path:
    path = root / "broadcast" / script / str(CHAIN) / "run-latest.json"
    path.parent.mkdir(parents=True)
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload))
    return path


def _run(proxy=PROXY):
    return {
        "transactions": [
            {"transactionType": "CREATE", "contractName": "BioRigCoreV5", "contractAddress": IMPL, "hash": "0x01"},
            {"transactionType": "CREATE", "contractName": "ERC1967Proxy", "contractAddress": proxy, "hash": "0x02"},
            {"transactionType": "CALL", "contractName": "ERC1967Proxy", "contractAddress": proxy, "hash": "0x03"},
        ],
        "receipts": [{"transactionHash": "0x02", "blockNumber": "0x23c65b4"}],
    }


def test_deployall_broadcast_wins_over_env(tmp_path):
    _broadcast(tmp_path, "DeployAll.s.sol", _run())
    r = resolve_proxy(tmp_path, {"PROXY_ADDRESS": "0x" + "11" * 20})
    assert r.address == PROXY  # the proxy, not the implementation
    assert r.source == f"broadcast/DeployAll.s.sol/{CHAIN}/run-latest.json"
    assert r.deploy_block == 0x23C65B4
    assert r.skipped == ()


def test_deploybiorig_broadcast_is_second(tmp_path):
    other = "0x" + "ab" * 20
    _broadcast(tmp_path, "DeployBioRig.s.sol", _run(other))
    r = resolve_proxy(tmp_path, {"PROXY_ADDRESS": "0x" + "11" * 20})
    assert r.address == other
    assert "DeployBioRig.s.sol" in r.source
    assert "DeployAll.s.sol" in r.skipped[0] and "not found" in r.skipped[0]


def test_env_fallback_when_no_broadcast(tmp_path):
    r = resolve_proxy(tmp_path, {"PROXY_ADDRESS": PROXY.upper().replace("0X", "0x"), "PROXY_DEPLOY_BLOCK": "123"})
    assert r.address == PROXY
    assert r.source == ".env PROXY_ADDRESS"
    assert r.deploy_block == 123
    assert len(r.skipped) == 2


def test_malformed_broadcast_falls_through_with_reason(tmp_path):
    _broadcast(tmp_path, "DeployAll.s.sol", "{not json")
    r = resolve_proxy(tmp_path, {"PROXY_ADDRESS": PROXY})
    assert r.source == ".env PROXY_ADDRESS"
    assert "malformed JSON" in r.skipped[0]


def test_broadcast_without_proxy_is_skipped(tmp_path):
    run = _run()
    run["transactions"] = run["transactions"][:1]
    _broadcast(tmp_path, "DeployAll.s.sol", run)
    with pytest.raises(ProxyResolutionError) as exc:
        resolve_proxy(tmp_path, {})
    msg = str(exc.value)
    assert "no ERC1967Proxy creation" in msg
    assert "PROXY_ADDRESS: not set" in msg
    assert "add PROXY_ADDRESS" in msg


def test_invalid_env_address_fails_loudly(tmp_path):
    with pytest.raises(ProxyResolutionError, match="not a 20-byte hex address"):
        resolve_proxy(tmp_path, {"PROXY_ADDRESS": "0x1234"})


def test_bad_contract_address_in_broadcast(tmp_path):
    _broadcast(tmp_path, "DeployAll.s.sol", _run("0xnothex"))
    with pytest.raises(ProxyResolutionError, match="invalid contractAddress"):
        resolve_proxy(tmp_path, {})


def test_load_dotenv_parsing(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# c\nA=1\nexport B = two \nC=\"q v\"\nbad line\nA=3\n")
    assert load_dotenv(p) == {"A": "3", "B": "two", "C": "q v"}
    assert load_dotenv(tmp_path / "missing") == {}


def test_settings_repr_never_shows_key(tmp_path):
    key = "0x" + "ab" * 32
    (tmp_path / ".env").write_text(f"PRIVATE_KEY={key}\nPROXY_ADDRESS={PROXY}\n")
    s = load_settings(tmp_path)
    assert s.private_key == key
    assert key not in repr(s) and key not in str(s) and "<set>" in repr(s)


def test_real_repo_resolves_live_proxy():
    r = resolve_proxy(REPO, {})
    assert r.address == PROXY
    assert "DeployAll.s.sol" in r.source


# --------------------------------------------------------------------------- hosted deployment


@pytest.fixture(autouse=True)
def _clean_config_env(monkeypatch):
    """Keep the process environment out of every test here, so precedence is what is under test."""
    for key in CONFIG_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_static_deployment_is_the_last_resort(tmp_path):
    (tmp_path / "dashboard").mkdir()
    (tmp_path / "dashboard" / "deployment.json").write_text(
        json.dumps({"chain_id": CHAIN, "proxy_address": PROXY.upper().replace("0X", "0x"),
                    "proxy_deploy_block": 37511856}))
    r = resolve_proxy(tmp_path, {"PROXY_ADDRESS": ""})
    assert r.address == PROXY
    assert r.source == "dashboard/deployment.json (static fallback)"
    assert r.deploy_block == 37511856
    assert len(r.skipped) == 3  # both broadcasts, then the empty env var


def test_static_deployment_never_beats_a_configured_address(tmp_path):
    (tmp_path / "dashboard").mkdir()
    (tmp_path / "dashboard" / "deployment.json").write_text(
        json.dumps({"chain_id": CHAIN, "proxy_address": "0x" + "ab" * 20}))
    r = resolve_proxy(tmp_path, {"PROXY_ADDRESS": PROXY})
    assert r.address == PROXY and r.source == ".env PROXY_ADDRESS"


def test_static_deployment_for_another_chain_is_refused(tmp_path):
    (tmp_path / "dashboard").mkdir()
    (tmp_path / "dashboard" / "deployment.json").write_text(
        json.dumps({"chain_id": 42220, "proxy_address": PROXY}))
    with pytest.raises(ProxyResolutionError, match="records chain 42220, not 11142220"):
        resolve_proxy(tmp_path, {})


def test_committed_deployment_json_matches_the_live_broadcast():
    """The static record must agree with the broadcast that actually deployed it, or the fallback lies."""
    from dashboard.config import _proxy_from_deployment

    addr, block = _proxy_from_deployment(REPO / "dashboard" / "deployment.json", CHAIN)
    assert addr == PROXY and block == 37511856
    broadcast = json.loads((REPO / "broadcast" / "DeployAll.s.sol" / str(CHAIN) / "run-latest.json").read_text())
    proxy_tx = [t for t in broadcast["transactions"]
                if t.get("contractName") == "ERC1967Proxy"
                and t.get("transactionType") in ("CREATE", "CREATE2")][-1]
    assert proxy_tx["contractAddress"].lower() == addr


def test_hosted_secrets_reach_the_settings(tmp_path):
    (tmp_path / ".env").write_text(f"PROXY_ADDRESS={PROXY}\n")
    s = load_settings(tmp_path, secrets={"PRIVATE_KEY": "0x" + "cd" * 32, "ALLOW_MINT": "false",
                                         "RPC_URL": "https://rpc.example", "CHAIN_ID": str(CHAIN)})
    assert s.private_key == "0x" + "cd" * 32
    assert s.allow_mint is False
    assert s.rpc_url == "https://rpc.example"
    assert "PRIVATE_KEY" not in repr(s) or "0x" + "cd" * 32 not in repr(s)


def test_secrets_beat_the_env_file_but_not_the_process_environment(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(f"PROXY_ADDRESS={PROXY}\nRPC_URL=https://from-file\n")
    assert load_settings(tmp_path, secrets={"RPC_URL": "https://from-secrets"}).rpc_url == "https://from-secrets"
    monkeypatch.setenv("RPC_URL", "https://from-process")
    assert load_settings(tmp_path, secrets={"RPC_URL": "https://from-secrets"}).rpc_url == "https://from-process"


def test_allow_mint_defaults_to_on_and_parses_off(tmp_path):
    (tmp_path / ".env").write_text(f"PROXY_ADDRESS={PROXY}\n")
    assert load_settings(tmp_path).allow_mint is True
    for value, expected in (("false", False), ("False", False), ("0", False), ("no", False), ("off", False),
                            ("true", True), ("1", True), ("yes", True), ("on", True), ("", True),
                            ("junk", False)):
        assert load_settings(tmp_path, secrets={"ALLOW_MINT": value}).allow_mint is expected, value


def test_hosted_secrets_are_empty_and_silent_without_a_secrets_file():
    from dashboard.config import hosted_secrets

    assert hosted_secrets() == {}
