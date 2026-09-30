import json
from pathlib import Path

import pytest

from dashboard.config import ProxyResolutionError, Settings, load_dotenv, resolve_proxy, load_settings

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
