"""Phase 0: fail-closed configuration and the boot assertion."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from relay.__main__ import main
from relay.config import ConfigError, Limits, Retry, load_config

from .conftest import TEST_KEY, FakeBroadcaster, base_env

REPO = Path(__file__).resolve().parents[2]


def test_the_plans_numbers_are_the_defaults(tmp_path):
    c = load_config(base_env(tmp_path))
    lim = c.limits
    assert (lim.collision_radius_m, lim.max_accuracy_m, lim.max_trees_per_cell) == (20.0, 30.0, 4)
    assert (lim.per_session, lim.per_ip_hour, lim.per_ip_day, lim.per_planter_day, lim.global_per_day) == \
        (3, 5, 20, 10, 200)
    assert c.retry.backoff_s == (2.0, 10.0, 45.0) and c.h3_resolution == 12
    assert c.dry_run is False and c.paused is False and c.chain_id == 42220
    assert c.proxy.address == "0x04db169ddf8abb80943161c01b2a71dc40384e64"


def test_limits_are_config_driven(tmp_path):
    c = load_config(base_env(tmp_path, COLLISION_RADIUS_M="15", LIMIT_PER_IP_HOUR="9", BACKOFF_S="1,2"))
    assert c.limits.collision_radius_m == 15.0 and c.limits.per_ip_hour == 9 and c.retry.max_attempts == 3


def test_no_signer_refuses_to_start(tmp_path):
    env = base_env(tmp_path)
    del env["RELAY_VERIFIER_KEY"]
    with pytest.raises(ConfigError, match="RELAY_VERIFIER_KEY is not set"):
        load_config(env)
    with pytest.raises(ConfigError):
        load_config(base_env(tmp_path, RELAY_VERIFIER_KEY="0x1234"))


@pytest.mark.parametrize("key", ["DRY_RUN", "PAUSED"])
def test_an_unrecognised_flag_refuses_rather_than_guessing(tmp_path, key):
    with pytest.raises(ConfigError, match=key):
        load_config(base_env(tmp_path, **{key: "maybe"}))


def test_repr_never_shows_the_key(tmp_path):
    c = load_config(base_env(tmp_path, RELAY_ADMIN_TOKEN="t" * 40))
    assert TEST_KEY[2:] not in repr(c) and "t" * 40 not in repr(c)


def test_process_without_a_key_exits_non_zero_and_names_the_reason(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("RELAY_")}
    env["RELAY_DB"] = str(tmp_path / "x.db")
    proc = subprocess.run([sys.executable, "-m", "relay", "--check"], cwd=REPO, env=env, capture_output=True,
                          text=True, timeout=60)
    assert proc.returncode == 2
    assert "refusing to start" in proc.stderr and "RELAY_VERIFIER_KEY" in proc.stderr
    assert not (tmp_path / "x.db").exists()


def test_a_key_without_verifier_role_exits_non_zero(tmp_path, capsys):
    rc = main(["--check"], env=base_env(tmp_path), broadcaster_factory=lambda c: FakeBroadcaster(verifier=False))
    assert rc == 3
    assert "does not hold VERIFIER_ROLE" in capsys.readouterr().err


def test_wrong_chain_exits_non_zero(tmp_path, capsys):
    rc = main(["--check"], env=base_env(tmp_path), broadcaster_factory=lambda c: FakeBroadcaster(rpc_chain=1))
    assert rc == 3 and "reports chain 1" in capsys.readouterr().err


def test_the_verifier_boots_and_health_reports_chain_and_role(tmp_path, capsys):
    rc = main(["--check"], env=base_env(tmp_path), broadcaster_factory=lambda c: FakeBroadcaster())
    out = capsys.readouterr().out
    assert rc == 0
    assert '"chain_id": 42220' in out and '"signer_is_verifier": true' in out


def test_a_store_bound_to_another_chain_refuses(tmp_path, capsys):
    main(["--check"], env=base_env(tmp_path), broadcaster_factory=lambda c: FakeBroadcaster())
    rc = main(["--check"], env=base_env(tmp_path, RELAY_CHAIN_ID="11142220"),
              broadcaster_factory=lambda c: FakeBroadcaster(rpc_chain=11142220))
    assert rc == 4


def test_the_relay_never_imports_streamlit():
    code = ("import sys, relay.service, relay.broadcaster, relay.seed, relay.__main__; "
            "sys.exit(1 if 'streamlit' in sys.modules else 0)")
    proc = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr or "streamlit was imported"
