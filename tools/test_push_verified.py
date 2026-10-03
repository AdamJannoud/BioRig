"""scripts/push-verified.sh must refuse a stale base in seconds, before the expensive proof runs.

The script's own control flow is what runs here, against throwaway local remotes, with `tools/clean_clone_proof.py`
stubbed out (the stub records that it was called and exits 0). No network, no key, and fast enough for the acceptance
gate's unit step.

The case that motivated this: on 3 Oct 2026 a push spent the whole clean-clone proof and then died at stage 2 with
`! [rejected] ... (fetch first)`, because the local commit branched from an older base than the remote's main.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "push-verified.sh"
FF_LIB = REPO_ROOT / "scripts" / "lib" / "fast_forward_check.sh"

# Stand-in for the real proof tool: records the call, then succeeds. The two proofs the script makes (local, then of
# the pushed tip) are distinguishable by their arguments, so a test can tell whether they ran at all and in what order.
PROOF_STUB = """\
import os, sys
with open(os.environ["PROOF_MARKER"], "a", encoding="utf-8") as fh:
    fh.write(" ".join(sys.argv[1:]) + "\\n")
sys.exit(0)
"""


def _env() -> dict[str, str]:
    """Hermetic: the sandbox's ambient git config sets identity, hooks and branch names; a test must not inherit it."""
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = "BioRig Tests"
    env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = "tests@example.invalid"
    env.pop("PRIVATE_KEY", None)
    return env


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=_env())
    return done.stdout.strip()


@dataclass
class Rig:
    origin: Path  # the bare remote the script pushes to
    work: Path  # the checkout the script runs in
    marker: Path  # where the proof stub records its calls
    tmp: Path


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    """A bare `origin` with one commit on main, and a checkout holding the script under test plus the proof stub."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "--initial-branch=main", str(origin))
    work = tmp_path / "work"
    _git(tmp_path, "clone", str(origin), str(work))

    script = work / "scripts" / "push-verified.sh"
    script.parent.mkdir()
    script.write_bytes(SCRIPT.read_bytes())  # the script under test, byte for byte
    script.chmod(0o755)
    lib = work / "scripts" / "lib" / "fast_forward_check.sh"
    lib.parent.mkdir()
    lib.write_bytes(FF_LIB.read_bytes())  # the shared pre-flight the script sources
    (work / "tools").mkdir()
    (work / "tools" / "clean_clone_proof.py").write_text(PROOF_STUB, encoding="utf-8")

    _commit(work, "base")
    _git(work, "push", "origin", "main")
    return Rig(origin=origin, work=work, marker=tmp_path / "proof-calls", tmp=tmp_path)


def _commit(repo: Path, message: str) -> str:
    log = repo / "log.txt"
    log.write_text((log.read_text(encoding="utf-8") if log.exists() else "") + message + "\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _advance_remote(rig: Rig, message: str) -> str:
    """Move origin's main on from a second clone, the way a colleague's push would."""
    other = rig.tmp / f"other-{uuid4().hex[:8]}"
    _git(rig.tmp, "clone", str(rig.origin), str(other))
    sha = _commit(other, message)
    _git(other, "push", "origin", "main")
    return sha


def _remote_main(rig: Rig) -> str:
    return _git(rig.tmp, "ls-remote", str(rig.origin), "refs/heads/main").split()[0]


def _run(rig: Rig, *args: str) -> subprocess.CompletedProcess[str]:
    env = _env() | {"PROOF_MARKER": str(rig.marker)}
    return subprocess.run(
        ["bash", str(rig.work / "scripts" / "push-verified.sh"), *args],
        cwd=rig.work,
        capture_output=True,
        text=True,
        env=env,
    )


def _proof_calls(rig: Rig) -> list[str]:
    if not rig.marker.exists():
        return []
    return [line for line in rig.marker.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_stale_base_fails_before_the_proof_runs(rig: Rig):
    remote_sha = _advance_remote(rig, "a colleague's commit")
    local_sha = _commit(rig.work, "my commit")
    tracking = _git(rig.work, "rev-parse", "refs/remotes/origin/main")
    assert tracking != remote_sha, "precondition: the checkout's tracking ref is stale, the check must read the remote"

    result = _run(rig)

    assert result.returncode != 0
    assert "stage 0/3: pre-flight" in result.stdout
    assert "stage 1/3" not in result.stdout, "the proof must not have started"
    assert remote_sha[:8] in result.stdout, "the refusal names the remote sha"
    assert local_sha[:8] in result.stdout
    assert "not a fast-forward" in result.stdout
    assert "git rebase" in result.stdout, "the refusal says how to fix it"
    assert "do not force-push" in result.stdout
    assert _proof_calls(rig) == [], "the expensive proof never ran"
    assert _remote_main(rig) == remote_sha, "nothing was pushed"


def test_fast_forward_pushes_and_proves_both_sides(rig: Rig):
    local_sha = _commit(rig.work, "my commit")

    result = _run(rig)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "the push fast-forwards it" in result.stdout
    assert "PUSH VERIFIED" in result.stdout
    calls = _proof_calls(rig)
    assert len(calls) == 2, calls
    assert "--source local" in calls[0] and local_sha in calls[0]
    assert "--source github" in calls[1] and local_sha in calls[1]
    assert _remote_main(rig) == local_sha


def test_a_remote_without_main_is_created(rig: Rig):
    _git(rig.origin, "update-ref", "-d", "refs/heads/main")
    local_sha = _commit(rig.work, "first commit")

    result = _run(rig)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "has no main yet" in result.stdout
    assert _remote_main(rig) == local_sha
    assert len(_proof_calls(rig)) == 2


def test_an_already_pushed_commit_is_still_proved_from_the_remote(rig: Rig):
    head = _git(rig.work, "rev-parse", "HEAD")

    result = _run(rig)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "is already" in result.stdout
    assert _remote_main(rig) == head
    assert len(_proof_calls(rig)) == 2


def test_the_script_still_honours_a_named_remote(rig: Rig):
    _git(rig.work, "remote", "add", "upstream", str(rig.origin))
    _advance_remote(rig, "a colleague's commit")

    result = _run(rig, "upstream")

    assert result.returncode != 0
    assert "stage 0/3: pre-flight on upstream main" in result.stdout
    assert _proof_calls(rig) == []
