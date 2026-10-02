"""Prove that a pristine clone of BioRig builds and passes its acceptance gate by following the README, nothing else.

    python3 tools/clean_clone_proof.py                                  # GitHub's main tip, key from the usual places
    python3 tools/clean_clone_proof.py --source local --commit HEAD     # a local commit, before it is pushed
    python3 tools/clean_clone_proof.py --no-key --json proof.json       # key-free: a partial run, said so everywhere

What a reader gets is a plain `git clone` (no --recurse-submodules) and the README. So this clones exactly that way,
into a temp directory outside the checkout, checks the clone out at the source commit, and asserts its commit and
tree equal the source's. It then parses the `## Quick start` bash fence out of the clone's README.md and runs its
lines in order in the clone, stopping at the first failure: the proof runs the documented quick start, not a private
recipe, so a step the README forgets (the submodule init, a missing install) fails here first. A fence that cannot
be found or parsed is a FAIL, never a skip.

Lines are run one at a time through bash; exports and `cd` carry over to the next line, as in a terminal. Two kinds
of line get special handling, both visible in the per-line table:
  key placeholder  `PRIVATE_KEY=<...>` is given the real key through a child-only environment variable, so the key
                   is never printed, written to disk or put on a command line. Without a key the line is SKIPPED.
  server           a line that starts a long-running server (`streamlit run`) is started in the background, must
                   answer its health endpoint, and is then stopped. Its documented port is used when free.
The gate line (`bash scripts/verify-demo.sh`) is run once, as the gate: key-free (VERIFY_ALLOW_NO_KEY=1) when no key
is available. If the fence has no gate line, the gate runs after the quick start.

Key, first hit wins: --key-file, PRIVATE_KEY in the environment, PRIVATE_KEY in <repo-root>/.env. --no-key ignores
all three. The clone never receives the .env file, so it runs on the repository's default chain.

Verdict: PASS (exit 0) only when every quick start line and every gate step ran and passed and the identity checks
hold. A run that skipped anything is PARTIAL (exit 3), never PASS: the skipped steps are listed in the output and
the JSON. FAIL is exit 1, a refusal or setup error exit 2. Refuses to run when CLEAN_CLONE_PROOF=1 is already set
(no nested proofs, e.g. a gate that someday invokes this), and exports it for every child.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

GITHUB_URL = "https://github.com/AdamJannoud/BioRig"
GITHUB_API = "https://api.github.com/repos/AdamJannoud/BioRig/git/commits/"
REPO_ROOT = Path(__file__).resolve().parents[1]
KEY_VAR = "CLEAN_CLONE_PROOF_KEY"  # child-only: set for the placeholder line alone, dropped from the carried env
KEY_RE = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")
PLACEHOLDER_RE = re.compile(r"<[^<>\s][^<>]*>")
KEY_PLACEHOLDER_RE = re.compile(r"\b(PRIVATE_KEY)=<[^<>]+>")
SERVER_RE = re.compile(r"\bstreamlit\s+run\b")
GATE_RE = re.compile(r"(^|\s)(bash\s+)?(\./)?scripts/verify-demo\.sh\b")
SKIPPED_RE = re.compile(r"^SKIPPED \(no key\): step (\S+)", re.M)
STEP_RE = re.compile(r"^== (.+)$", re.M)
FULL_BANNER = "ALL DEMO CHECKS PASSED"
# Settings the dashboard and the gate read: a reader's clone starts without them, so the proof does too.
SCRUBBED = ("PRIVATE_KEY", "CHAIN_ID", "RPC_URL", "EXPLORER_URL", "PROXY_ADDRESS", "PROXY_DEPLOY_BLOCK", "ALLOW_MINT",
            "VERIFY_ALLOW_NO_KEY", "KEY_FILE", "VIRTUAL_ENV", "DEMO_PORT", KEY_VAR)


class Refusal(Exception):
    """Setup cannot proceed (nested proof, unknown commit, bad key, clone failed). Exit 2."""


@dataclass
class LineResult:
    n: int
    line: str  # as displayed: the key placeholder is never expanded here
    kind: str  # shell | key | server | gate
    exit: int | None  # None: not run (skipped, or after the first failure)
    status: str  # ok | FAIL | SKIPPED (no key) | not run
    seconds: float = 0.0
    note: str = ""
    tail: list[str] = field(default_factory=list)  # the last output lines of a failed line


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, capture_output=True, **kw)


def git(*args: str, cwd: Path | None = None, env: dict | None = None) -> str:
    r = run(["git", *args], cwd=cwd, env=env)
    if r.returncode != 0:
        raise Refusal(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def child_env() -> dict[str, str]:
    """The environment a reader's terminal would have: no GIT_* (a pre-push hook sets GIT_DIR, which would aim
    every git command in the clone at the pushing repo), none of the dashboard's settings."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k not in SCRUBBED}
    env["CLEAN_CLONE_PROOF"] = "1"
    return env


def resolve_key(args) -> tuple[str | None, str]:
    """(key, where it came from). Never returns or prints anything derived from the value except its source."""
    if args.no_key:
        return None, "none (--no-key)"
    candidates = []
    if args.key_file:
        candidates.append((Path(args.key_file).read_text(), f"--key-file {args.key_file}"))
    if os.environ.get("PRIVATE_KEY", "").strip():
        candidates.append((os.environ["PRIVATE_KEY"], "PRIVATE_KEY in the environment"))
    dotenv = Path(args.repo_root) / ".env"
    if dotenv.is_file():
        for raw in dotenv.read_text().splitlines():
            if raw.startswith("PRIVATE_KEY=") and raw.split("=", 1)[1].strip():
                candidates.append((raw.split("=", 1)[1].strip().strip("'\""), f"PRIVATE_KEY in {dotenv}"))
    if not candidates:
        return None, "none found (--key-file, PRIVATE_KEY, <repo-root>/.env)"
    key, source = candidates[0]
    key = key.strip()
    if not KEY_RE.match(key):
        raise Refusal(f"the key from {source} is not 64 hex digits (with or without 0x): {len(key)} characters")
    return key, source


def quick_start_lines(readme: Path) -> list[str]:
    """The commands in the first bash fence under `## Quick start`, continuation lines joined, comment-only and blank
    lines dropped. Raises Refusal-free ValueError when the section or fence is missing: the caller makes it a FAIL."""
    if not readme.is_file():
        raise ValueError("README.md is missing from the clone")
    text = readme.read_text().splitlines()
    try:
        start = next(i for i, l in enumerate(text) if re.match(r"^##\s+Quick start\s*$", l, re.I))
    except StopIteration:
        raise ValueError("README.md has no '## Quick start' section") from None
    fence_open = None
    for i in range(start + 1, len(text)):
        if text[i].startswith("## "):
            break
        if re.match(r"^```(bash|sh|shell)\s*$", text[i].strip()):
            fence_open = i
            break
    if fence_open is None:
        raise ValueError("the '## Quick start' section has no ```bash fence")
    body = []
    for i in range(fence_open + 1, len(text)):
        if text[i].strip().startswith("```"):
            break
        body.append(text[i])
    else:
        raise ValueError("the quick start's ```bash fence is never closed")
    lines, pending = [], ""
    for raw in body:
        if raw.rstrip().endswith("\\"):
            pending += raw.rstrip()[:-1] + " "
            continue
        joined = (pending + raw).strip()
        pending = ""
        if joined and not joined.startswith("#"):
            lines.append(joined)
    if pending.strip():
        raise ValueError("the quick start fence ends in a dangling line continuation")
    if not lines:
        raise ValueError("the quick start fence holds no commands")
    return lines


def display(line: str) -> str:
    return KEY_PLACEHOLDER_RE.sub(lambda m: f"{m.group(1)}=<redacted>", line)


def port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Runner:
    """Runs quick start lines in the clone, carrying exports and the working directory from one line to the next."""

    def __init__(self, clone: Path, key: str | None, workdir: Path):
        self.cwd = str(clone)
        self.env = child_env()
        self.key = key
        self.workdir = workdir

    def _redact(self, text: str) -> str:
        if self.key:
            bare = self.key.lower().removeprefix("0x")
            text = re.sub(re.escape(bare), "<redacted>", text, flags=re.I)
        return text

    def _stream(self, proc: subprocess.Popen) -> list[str]:
        """Echo the child's output as it arrives (redacted) and keep it for parsing."""
        kept = []
        for raw in proc.stdout:
            line = self._redact(raw)
            sys.stdout.write("    " + line)
            sys.stdout.flush()
            kept.append(line.rstrip("\n"))
        proc.wait()
        return kept

    def shell(self, command: str, extra_env: dict | None = None) -> tuple[int, list[str]]:
        """One line through bash. The line runs with the state pipe closed (so a background child cannot hold it
        open), then the shell reports its working directory and environment over that pipe."""
        r, w = os.pipe()
        script = f"{{ {command}\n}} {w}>&-\n__rc=$?\n{{ printf '%s\\0' \"$PWD\"; env -0; }} >&{w}\nexit $__rc\n"
        env = dict(self.env, **(extra_env or {}))
        proc = subprocess.Popen(["bash", "-c", script], cwd=self.cwd, env=env, pass_fds=(w,), text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        os.close(w)
        state: list[bytes] = []
        reader = threading.Thread(target=lambda: state.append(os.fdopen(r, "rb").read()))
        reader.start()
        out = self._stream(proc)
        reader.join()
        blob = state[0] if state else b""
        if blob:
            parts = blob.decode(errors="replace").split("\0")
            self.cwd = parts[0] or self.cwd
            carried = dict(p.split("=", 1) for p in parts[1:] if "=" in p)
            carried.pop(KEY_VAR, None)  # the key reaches the next line only through what the line itself exported
            for k in ("_", "SHLVL", "OLDPWD", "PWD"):
                carried.pop(k, None)
            self.env = carried
        return proc.returncode, out

    def server(self, command: str) -> tuple[int, list[str], str]:
        """Start a long-running server line, require its health endpoint to answer, then stop it."""
        m = re.search(r"localhost:(\d+)", command)
        documented = int(m.group(1)) if m else 8501
        port, note = documented, f"answered /_stcore/health on its documented port {documented}"
        env = dict(self.env, STREAMLIT_SERVER_HEADLESS="true", STREAMLIT_BROWSER_GATHER_USAGE_STATS="false")
        if not port_free(documented):
            port = free_port()
            env["STREAMLIT_SERVER_PORT"] = str(port)
            note = f"documented port {documented} was busy on this machine; ran on {port} (STREAMLIT_SERVER_PORT)"
        log = self.workdir / "server-line.log"
        with open(log, "w") as fh:
            proc = subprocess.Popen(["bash", "-c", command], cwd=self.cwd, env=env, stdout=fh, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, start_new_session=True)
        healthy = False
        try:
            deadline = time.time() + 90
            while time.time() < deadline and proc.poll() is None:
                try:
                    urllib.request.urlopen(f"http://localhost:{port}/_stcore/health", timeout=2).read()
                    healthy = True
                    break
                except OSError:
                    time.sleep(0.5)
        finally:
            try:
                os.killpg(proc.pid, 15)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, 9)
        out = self._redact(log.read_text(errors="replace")).splitlines()
        for line in out[-8:]:
            print("    " + line)
        if not healthy:
            return 1, out, f"never answered /_stcore/health on port {port}"
        return 0, out, note


def gate_env_for(key: str | None) -> tuple[dict, str]:
    extra, notes = {}, []
    if key is None:
        extra["VERIFY_ALLOW_NO_KEY"] = "1"
        notes.append("key-free (VERIFY_ALLOW_NO_KEY=1)")
    if not port_free(8599):
        extra["DEMO_PORT"] = str(free_port())
        notes.append(f"gate default port 8599 busy; DEMO_PORT={extra['DEMO_PORT']}")
    if os.environ.get("SKIP_RENDER") == "1":
        extra["SKIP_RENDER"] = "1"
        notes.append("SKIP_RENDER=1 passed through: step 5 probed an existing mp4 instead of rendering one")
    return extra, "; ".join(notes)


def parse_gate(out: list[str], rc: int) -> dict:
    text = "\n".join(out)
    steps = STEP_RE.findall(text)
    return {
        "exit": rc,
        "steps_started": steps,
        "skipped_steps": SKIPPED_RE.findall(text),
        "full_banner": any(l.strip() == FULL_BANNER for l in out),
        "failing_step": (steps[-1] if steps else "before step 1") if rc != 0 else None,
        "banner": next((l.strip() for l in reversed(out) if l.strip()), ""),
    }


def source_identity(args, env: dict) -> tuple[str, str, str]:
    """(commit sha, tree sha, description of the source) for the commit the clone must equal."""
    repo = Path(args.repo_root)
    if args.source == "local":
        sha = git("rev-parse", "--verify", f"{args.commit or 'HEAD'}^{{commit}}", cwd=repo, env=env)
        return sha, git("rev-parse", f"{sha}^{{tree}}", cwd=repo, env=env), f"file://{repo}"
    url = args.remote_url
    out = git("ls-remote", url, f"refs/heads/{args.ref}", env=env)
    if not out:
        raise Refusal(f"{url} has no refs/heads/{args.ref}")
    sha = out.split()[0]
    if args.commit and not sha.startswith(args.commit):
        raise Refusal(f"GitHub's {args.ref} tip is {sha}, not the expected {args.commit}")
    # The tree comes from somewhere other than the clone under test: the local object store when it has the commit,
    # otherwise GitHub's API.
    if run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=repo, env=env).returncode == 0:
        tree = git("rev-parse", f"{sha}^{{tree}}", cwd=repo, env=env)
    elif url == GITHUB_URL:
        with urllib.request.urlopen(GITHUB_API + sha, timeout=20) as resp:
            tree = json.load(resp)["tree"]["sha"]
    else:
        raise Refusal(f"{sha} is in neither the local object store nor GitHub's API: no independent tree to compare")
    return sha, tree, url


def default_workdir() -> str | None:
    if os.environ.get("CLEAN_CLONE_PROOF_WORKDIR"):
        return os.environ["CLEAN_CLONE_PROOF_WORKDIR"]
    return "/var/tmp" if os.path.isdir("/var/tmp") else None


def print_table(rows: list[LineResult]) -> None:
    print("\nquick start, line by line:")
    print(f"  {'#':>2}  {'exit':>4}  {'status':<17} line")
    for r in rows:
        ex = "-" if r.exit is None else str(r.exit)
        print(f"  {r.n:>2}  {ex:>4}  {r.status:<17} {r.line}")
        if r.note:
            print(f"  {'':>2}  {'':>4}  {'':<17}   ({r.note})")


def prove(args) -> tuple[str, dict]:
    env = child_env()
    record: dict = {"source": args.source, "ref": args.ref, "requested_commit": args.commit, "started": time.time()}
    key, key_source = resolve_key(args)
    record["key"] = key_source
    sha, tree, origin = source_identity(args, env)
    record.update(source_url=origin, source_sha=sha, source_tree=tree)
    print(f"source        {origin}  ({args.source}{', ref ' + args.ref if args.source == 'github' else ''})")
    print(f"source commit {sha}\nsource tree   {tree}\nkey           {key_source}")

    workdir = Path(tempfile.mkdtemp(prefix="clean-clone-proof-", dir=args.workdir))
    if workdir.resolve().is_relative_to(Path(args.repo_root).resolve()):
        shutil.rmtree(workdir)
        raise Refusal("the clone directory would sit inside the checkout; pick a --workdir outside it")
    clone = workdir / "BioRig"
    record["clone_dir"] = str(clone)
    try:
        # A plain clone, exactly what a reader runs: no --recurse-submodules.
        git("clone", "--quiet", origin, str(clone), env=env)
        if run(["git", "checkout", "--quiet", "--detach", sha], cwd=clone, env=env).returncode != 0:
            git("fetch", "--quiet", "origin", sha, cwd=clone, env=env)  # a pushed sha no branch points at yet
            git("checkout", "--quiet", "--detach", sha, cwd=clone, env=env)
        clone_sha = git("rev-parse", "HEAD", cwd=clone, env=env)
        clone_tree = git("rev-parse", "HEAD^{tree}", cwd=clone, env=env)
        record.update(clone_sha=clone_sha, clone_tree=clone_tree,
                      identity_ok=clone_sha == sha and clone_tree == tree)
        print(f"clone commit  {clone_sha}  {'==' if clone_sha == sha else '!='} source")
        print(f"clone tree    {clone_tree}  {'==' if clone_tree == tree else '!='} source")
        print(f"clone dir     {clone}{' (kept)' if args.keep else ' (removed afterwards)'}")
        if not record["identity_ok"]:
            record.update(verdict="FAIL", failing_step="identity: the clone is not the source commit")
            return "FAIL", record
        return run_quick_start(args, record, clone, key, workdir)
    finally:
        if not args.keep:
            shutil.rmtree(workdir, ignore_errors=True)


def run_quick_start(args, record: dict, clone: Path, key: str | None, workdir: Path) -> tuple[str, dict]:
    try:
        lines = quick_start_lines(clone / "README.md")
    except ValueError as exc:
        record.update(verdict="FAIL", failing_step=f"quick start parse: {exc}", lines=[])
        print(f"\nFAIL: {exc}")
        return "FAIL", record
    for line in lines:
        if PLACEHOLDER_RE.search(KEY_PLACEHOLDER_RE.sub("", line.split(" #")[0])):
            record.update(verdict="FAIL", failing_step=f"quick start parse: unresolvable placeholder in: {line}")
            print(f"\nFAIL: a quick start line carries a placeholder this proof cannot fill: {line}")
            return "FAIL", record

    runner = Runner(clone, key, workdir)
    rows: list[LineResult] = []
    gate: dict | None = None
    failed: LineResult | None = None
    gate_extra, gate_note = gate_env_for(key)

    def run_gate(n: int, text: str, command: str) -> LineResult:
        nonlocal gate
        t0 = time.time()
        rc, out = runner.shell(command, gate_extra)
        gate = parse_gate(out, rc)
        status = "ok" if rc == 0 else "FAIL"
        note = gate_note
        if rc == 0 and gate["skipped_steps"]:
            note = f"{note}; gate skipped steps {' '.join(gate['skipped_steps'])}".lstrip("; ")
        return LineResult(n, text, "gate", rc, status, round(time.time() - t0, 1), note,
                          [] if rc == 0 else out[-40:])

    for n, line in enumerate(lines, 1):
        shown = display(line)
        if failed:
            rows.append(LineResult(n, shown, "shell", None, "not run"))
            continue
        print(f"\n--- [{n}/{len(lines)}] $ {shown}")
        t0 = time.time()
        if KEY_PLACEHOLDER_RE.search(line):
            if key is None:
                rows.append(LineResult(n, shown, "key", None, "SKIPPED (no key)", note="no key available"))
                print("    SKIPPED (no key)")
                continue
            command = KEY_PLACEHOLDER_RE.sub(lambda m: f'{m.group(1)}="${KEY_VAR}"', line)
            rc, out = runner.shell(command, {KEY_VAR: key})
            row = LineResult(n, shown, "key", rc, "ok" if rc == 0 else "FAIL", note="key supplied, not printed")
        elif GATE_RE.search(line):
            row = run_gate(n, shown, line)
        elif SERVER_RE.search(line):
            rc, out, note = runner.server(line)
            row = LineResult(n, shown, "server", rc, "ok" if rc == 0 else "FAIL", note=note)
        else:
            rc, out = runner.shell(line)
            row = LineResult(n, shown, "shell", rc, "ok" if rc == 0 else "FAIL")
        row.seconds = round(time.time() - t0, 1)
        if row.exit != 0:
            row.tail = row.tail or out[-40:]
            failed = row
        rows.append(row)

    if gate is None and not failed:
        print("\n--- [gate] $ bash scripts/verify-demo.sh   (the quick start has no gate line)")
        row = run_gate(len(lines) + 1, "bash scripts/verify-demo.sh  (after the quick start)", "bash scripts/verify-demo.sh")
        rows.append(row)
        if row.exit != 0:
            failed = row

    record["lines"] = [asdict(r) for r in rows]
    record["gate"] = gate
    skipped = [f"quick start line {r.n}: {r.line}" for r in rows if r.status.startswith("SKIPPED")]
    skipped += [f"gate step {s}" for s in (gate or {}).get("skipped_steps", [])]
    record["skipped"] = skipped
    print_table(rows)

    if failed:
        command = re.sub(r"\s+#.*$", "", failed.line)  # the README comment dropped
        where = f"quick start line {failed.n}: {command}"
        if failed.kind == "gate" and gate:
            where += f" (gate step {gate['failing_step']})"
        record.update(verdict="FAIL", failing_step=where)
    elif skipped or not (gate and gate["full_banner"]):
        record.update(verdict="PARTIAL", failing_step=None)
    else:
        record.update(verdict="PASS", failing_step=None)
    return record["verdict"], record


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--source", choices=("github", "local"), default="github")
    ap.add_argument("--ref", default="main", help="branch to resolve on GitHub (github source)")
    ap.add_argument("--remote-url", default=GITHUB_URL, help=f"the remote the github source clones (default {GITHUB_URL})")
    ap.add_argument("--commit", help="commit to prove (local source; default HEAD). With github: the expected tip")
    ap.add_argument("--no-key", action="store_true", help="key-free: skip the key steps; the verdict is PARTIAL")
    ap.add_argument("--key-file", help="file holding the deployer key (64 hex digits, 0x optional)")
    ap.add_argument("--keep", action="store_true", help="keep the clone directory afterwards")
    ap.add_argument("--json", help="write the proof record here")
    ap.add_argument("--repo-root", default=str(REPO_ROOT), help="the checkout (local source, .env key)")
    ap.add_argument("--workdir", default=default_workdir(),
                    help="parent directory for the clone, outside the checkout (default: $CLEAN_CLONE_PROOF_WORKDIR, "
                         "else /var/tmp: a clone plus its .venv is ~2 GB, more than this host's /tmp holds)")
    args = ap.parse_args(argv)

    if os.environ.get("CLEAN_CLONE_PROOF") == "1":
        print("clean_clone_proof: refusing to run: CLEAN_CLONE_PROOF=1 is already set (no nested proofs)",
              file=sys.stderr)
        return 2
    os.environ["CLEAN_CLONE_PROOF"] = "1"

    try:
        verdict, record = prove(args)
    except Refusal as exc:
        print(f"clean_clone_proof: {exc}", file=sys.stderr)
        verdict, record = "ERROR", {"verdict": "ERROR", "error": str(exc)}
    record["finished"] = time.time()

    print(f"\nskipped steps: {', '.join(record.get('skipped') or []) or 'none'}")
    if verdict == "PASS":
        print(f"CLEAN CLONE PROOF: PASS  {record['source_sha']}  every quick start line and every gate step ran green")
    elif verdict == "PARTIAL":
        print(f"CLEAN CLONE PROOF: PARTIAL  {record['source_sha']}  green, but NOT a full pass: "
              f"{len(record['skipped'])} skipped step(s) listed above")
    else:
        print(f"CLEAN CLONE PROOF: {verdict}  failing step: {record.get('failing_step') or record.get('error')}")
    if args.json:
        Path(args.json).write_text(json.dumps(record, indent=2) + "\n")
        print(f"record written to {args.json}")
    return {"PASS": 0, "FAIL": 1, "ERROR": 2, "PARTIAL": 3}[verdict]


if __name__ == "__main__":
    sys.exit(main())
