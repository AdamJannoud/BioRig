"""scripts/git-hooks/pre-push must refuse a stale base in seconds, before the clean-clone proof runs.

The hook's own control flow runs here, inside a real `git push` against a throwaway local bare remote, with
`tools/clean_clone_proof.py` stubbed (the stub records that it was called and writes the PASS record the hook expects,
so a push that is allowed completes without a key or a network). Small local remotes, so the suite stays in seconds.

Why the hook matters as much as the script: the hook proves the commit from a clean clone *before* the push goes out,
which takes minutes, and a stale base is rejected by the remote only afterwards. Refusing first is the whole point.

Where the hook is the only guard: git classifies a *plain* non-fast-forward push client-side - as long as the remote's
tip is in the local object store - and never calls the hook, so no proof is spent. It cannot classify a forced update
(which it would carry out, dropping the remote's commits) or a remote tip this checkout has never fetched. Those two are
what the pre-flight catches, and `test_a_plain_push_on_a_stale_base_costs_nothing_and_git_refuses_it` pins the boundary.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "scripts" / "git-hooks" / "pre-push"
SCRIPT = REPO_ROOT / "scripts" / "push-verified.sh"
FF_LIB = REPO_ROOT / "scripts" / "lib" / "fast_forward_check.sh"

# Stand-in for the real proof tool: records the call, then writes the PASS record the hook checks for and exits 0.
# STUB_TREE is the tree of the commit under proof, which the hook compares the record against.
PROOF_STUB = """\
import json, os, sys
argv = sys.argv[1:]
with open(os.environ["PROOF_MARKER"], "a", encoding="utf-8") as fh:
    fh.write(" ".join(argv) + "\\n")
path = argv[argv.index("--json") + 1] if "--json" in argv else None
if path:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"verdict": "PASS", "source": argv[argv.index("--source") + 1],
                   "source_sha": argv[argv.index("--commit") + 1],
                   "clone_tree": os.environ.get("STUB_TREE", ""), "identity_ok": True}, fh)
sys.exit(0)
"""


def _env() -> dict[str, str]:
    """Hermetic: the sandbox's ambient git config sets identity and hooks; a test must not inherit it."""
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


def _commit(repo: Path, message: str) -> str:
    log = repo / "log.txt"
    log.write_text((log.read_text(encoding="utf-8") if log.exists() else "") + message + "\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@dataclass
class Rig:
    origin: Path  # the bare remote that is pushed to
    work: Path  # the checkout holding the installed hook under test
    marker: Path  # where the proof stub records its calls
    tmp: Path


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    """A bare `origin` with one commit on main, and a checkout with the hook, the shared check and the proof stub."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "--initial-branch=main", str(origin))
    work = tmp_path / "work"
    _git(tmp_path, "clone", str(origin), str(work))

    hook = work / ".git" / "hooks" / "pre-push"
    hook.write_bytes(HOOK.read_bytes())  # the hook under test, byte for byte
    hook.chmod(0o755)
    lib = work / "scripts" / "lib" / "fast_forward_check.sh"
    lib.parent.mkdir(parents=True)
    lib.write_bytes(FF_LIB.read_bytes())
    (work / "tools").mkdir()
    (work / "tools" / "clean_clone_proof.py").write_text(PROOF_STUB, encoding="utf-8")
    (work / "scripts").mkdir(exist_ok=True)
    (work / "scripts" / "push-verified.sh").write_bytes(SCRIPT.read_bytes())

    _commit(work, "base")
    _git(work, "push", "--no-verify", "origin", "main")  # the remote starts with main, no hook run
    return Rig(origin=origin, work=work, marker=tmp_path / "proof-calls", tmp=tmp_path)


def _proof_calls(rig: Rig) -> list[str]:
    if not rig.marker.exists():
        return []
    return [line for line in rig.marker.read_text(encoding="utf-8").splitlines() if line.strip()]


def _push(rig: Rig, *args: str, cwd: Path | None = None, **extra_env: str) -> subprocess.CompletedProcess[str]:
    env = _env() | {"PROOF_MARKER": str(rig.marker)} | extra_env
    return subprocess.run(["git", "push", *args], cwd=cwd or rig.work, capture_output=True, text=True, env=env)


def _run_script(rig: Rig, *args: str, **extra_env: str) -> subprocess.CompletedProcess[str]:
    env = _env() | {"PROOF_MARKER": str(rig.marker)} | extra_env
    return subprocess.run(["bash", str(rig.work / "scripts" / "push-verified.sh"), *args],
                          cwd=rig.work, capture_output=True, text=True, env=env)


def _advance_remote(rig: Rig, message: str) -> str:
    """Move origin's main on from a second clone, the way a colleague's push would."""
    other = rig.tmp / f"other-{uuid4().hex[:8]}"
    _git(rig.tmp, "clone", str(rig.origin), str(other))
    sha = _commit(other, message)
    _git(other, "push", "--no-verify", "origin", "main")
    return sha


def _remote_main(rig: Rig) -> str:
    return _git(rig.tmp, "ls-remote", str(rig.origin), "refs/heads/main").split()[0]


def _tree(repo: Path, sha: str) -> str:
    return _git(repo, "rev-parse", f"{sha}^{{tree}}")


@pytest.mark.parametrize("force_flag", ["--force", "--force-with-lease"])
def test_a_forced_push_on_a_stale_base_is_refused_before_the_proof_runs(rig: Rig, force_flag: str):
    """The case that matters: git allows a forced update, so only this pre-flight stops it - and it stops it first."""
    remote_sha = _advance_remote(rig, "a colleague's commit")
    _git(rig.work, "fetch", "origin")  # the lease is satisfied and the tip can be named; the base is still stale
    local_sha = _commit(rig.work, "my commit")

    result = _push(rig, "origin", "main", force_flag, STUB_TREE=_tree(rig.work, local_sha))

    assert result.returncode != 0
    assert "not a fast-forward" in result.stderr
    assert remote_sha[:8] in result.stderr, "the refusal names the remote sha"
    assert local_sha[:8] in result.stderr
    assert "a colleague's commit" in result.stderr, "the refusal lists the work the remote has"
    assert "git rebase" in result.stderr, "the refusal says how to fix it"
    assert "do not force-push" in result.stderr
    assert _proof_calls(rig) == [], "the minutes-long proof never ran"
    assert _remote_main(rig) == remote_sha, "nothing was pushed"


def test_a_plain_push_on_a_stale_base_costs_nothing_and_git_refuses_it(rig: Rig):
    """Boundary, asserted rather than assumed: with the remote's tip in this checkout git classifies the update itself
    and never calls the hook, so no proof runs either. The hook's pre-flight exists for what git cannot stop."""
    remote_sha = _advance_remote(rig, "a colleague's commit")
    _git(rig.work, "fetch", "origin")
    local_sha = _commit(rig.work, "my commit")

    result = _push(rig, "origin", "main", STUB_TREE=_tree(rig.work, local_sha))

    assert result.returncode != 0
    assert "rejected" in result.stderr
    assert _proof_calls(rig) == [], "git refuses before the hook, so the proof never runs"
    assert _remote_main(rig) == remote_sha


def test_a_remote_tip_this_checkout_never_fetched_is_refused(rig: Rig):
    remote_sha = _advance_remote(rig, "a colleague's commit")
    local_sha = _commit(rig.work, "my commit")
    assert local_sha != remote_sha

    result = _push(rig, "origin", "main", STUB_TREE=_tree(rig.work, local_sha))

    assert result.returncode != 0
    assert "not a fast-forward" in result.stderr
    assert remote_sha[:8] in result.stderr
    assert "never been fetched" in result.stderr, "an absent remote tip reads as stale, not as an error"
    assert _proof_calls(rig) == [], "and the proof still never ran: git cannot classify this one itself"
    assert _remote_main(rig) == remote_sha


def test_a_fast_forward_push_proves_the_commit_and_lands(rig: Rig):
    _advance_remote(rig, "a colleague's commit")
    _git(rig.work, "fetch", "origin")
    _git(rig.work, "rebase", "refs/remotes/origin/main")  # caught up, as the refusal tells you to do
    local_sha = _commit(rig.work, "my commit")

    result = _push(rig, "origin", "main", STUB_TREE=_tree(rig.work, local_sha))

    assert result.returncode == 0, result.stdout + result.stderr
    calls = _proof_calls(rig)
    assert len(calls) == 1, calls
    assert "--source local" in calls[0] and local_sha in calls[0]
    assert _remote_main(rig) == local_sha


def test_a_branch_that_is_not_main_is_not_gated(rig: Rig):
    _advance_remote(rig, "a colleague's commit")
    base = _git(rig.work, "rev-parse", "HEAD")
    _git(rig.work, "checkout", "-q", "-b", "feature")
    local_sha = _commit(rig.work, "a feature commit")

    result = _push(rig, "origin", "feature", STUB_TREE=_tree(rig.work, local_sha))

    assert result.returncode == 0, result.stdout + result.stderr
    assert _proof_calls(rig) == [], "only main is gated"
    assert _git(rig.tmp, "ls-remote", str(rig.origin), "refs/heads/feature").split()[0] == local_sha
    assert base != local_sha


def test_a_deliberate_rewrite_is_allowed_only_on_purpose(rig: Rig):
    remote_sha = _advance_remote(rig, "a colleague's commit")
    _git(rig.work, "fetch", "origin")
    local_sha = _commit(rig.work, "my rewrite")
    tree = _tree(rig.work, local_sha)

    refused = _push(rig, "origin", "main", "--force", STUB_TREE=tree)

    assert refused.returncode != 0, "the override is what allows this, not the force flag"
    assert "not a fast-forward" in refused.stderr
    assert _proof_calls(rig) == []
    assert _remote_main(rig) == remote_sha

    allowed = _push(rig, "origin", "main", "--force", STUB_TREE=tree, BIORIG_ALLOW_NON_FAST_FORWARD="1")

    assert allowed.returncode == 0, allowed.stdout + allowed.stderr
    assert "BIORIG_ALLOW_NON_FAST_FORWARD=1" in allowed.stderr and "rewrites it" in allowed.stderr
    assert len(_proof_calls(rig)) == 1, "the override skips the pre-flight, never the proof"
    assert _remote_main(rig) == local_sha != remote_sha


def test_deleting_main_is_still_refused(rig: Rig):
    result = _push(rig, "origin", "--delete", "main")

    assert result.returncode != 0
    assert "refusing to delete main" in result.stderr
    assert _proof_calls(rig) == []


def test_the_script_and_the_hook_run_the_same_check_end_to_end(rig: Rig):
    """The pair together: the script proves and pushes, and the hook lets it through on the same verdict."""
    local_sha = _commit(rig.work, "my commit")

    result = _run_script(rig, STUB_TREE=_tree(rig.work, local_sha))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PUSH VERIFIED" in result.stdout
    assert _remote_main(rig) == local_sha
    calls = _proof_calls(rig)
    assert "fast-forward" in result.stdout
    assert len(calls) == 2, f"the two proofs the script makes, and no third from the hook: {calls}"


def test_both_push_paths_use_the_one_shared_check():
    """A guard against drift: neither caller may re-implement the ancestry test."""
    script = SCRIPT.read_text(encoding="utf-8")
    hook = HOOK.read_text(encoding="utf-8")
    lib = FF_LIB.read_text(encoding="utf-8")

    assert "merge-base --is-ancestor" in lib
    assert "cat-file -e" in lib
    for name, text in (("scripts/push-verified.sh", script), ("scripts/git-hooks/pre-push", hook)):
        assert "fast_forward_check.sh" in text, f"{name} does not source the shared check"
        assert "merge-base --is-ancestor" not in text, f"{name} re-implements the ancestry test"
        assert "cat-file -e" not in text, f"{name} re-implements the missing-object test"
