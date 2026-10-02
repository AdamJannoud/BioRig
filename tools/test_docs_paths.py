"""Pin tools/check_docs_paths.py: one passing and one failing fixture per check, the allowlist rules, and that files
are enumerated with `git ls-files` rather than read off the disk.

Every test builds its own throwaway repository under tmp_path (`git init` plus `git add`, no commit, so no git
identity is needed), so the suite runs the same in a fresh clone with no .venv, no .env and no submodules, and does
not depend on the real documents being clean.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools import check_docs_paths as cdp


def make_repo(root: Path, tracked: dict[str, str], untracked: dict[str, str] | None = None) -> Path:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for name, body in {**tracked, **(untracked or {})}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    if tracked:
        subprocess.run(["git", "-C", str(root), "add", "--", *tracked], check=True)
    return root


def check(capsys: pytest.CaptureFixture[str], root: Path, *docs: str, allow: str | None = None
          ) -> tuple[int, list[dict[str, object]]]:
    argv = ["--repo-root", str(root), "--json"]
    if docs:
        argv += ["--docs", *docs]
    if allow:
        argv += ["--allow", allow]
    code = cdp.main(argv)
    out = capsys.readouterr().out
    return code, (json.loads(out)["findings"] if code in (0, 1) else [])


def values(findings: list[dict[str, object]], kind: str) -> set[object]:
    return {f["value"] for f in findings if f["kind"] == kind}


# --- a. paths -------------------------------------------------------------------------------------------------

def test_paths_resolve_tracked_relative_basename_and_ignored(tmp_path, capsys):
    root = make_repo(tmp_path, {
        ".gitignore": ".env\n.venv/\ncache/\n",
        "tools/build.py": "",
        "pkg/README.md": "Run `tools/build.py`, see `notes.txt` next door and `sub/` below.\n",
        "pkg/notes.txt": "",
        "pkg/sub/x.json": "",
        "doc.md": ("Copy `.env.example` to `.env`; `.venv/bin/python tools/build.py` writes cache/out.json.\n"
                   "The builder is build.py, the subdir is `pkg/sub/`.\n"
                   "Skipped: https://example.com/a/b.py, `forge-std/Test.sol`, `<chain>/run.json`, "
                   "biorigdemo.streamlit.app, `owner/repo`, `/abs/path.py`, `~/x.sh`.\n"),
        ".env.example": "",
    })
    assert check(capsys, root, "doc.md", "pkg/README.md") == (0, [])


def test_paths_flag_a_missing_file(tmp_path, capsys):
    root = make_repo(tmp_path, {"tools/build.py": "", "doc.md": "Run `tools/biuld.py`, then read GUIDE.md.\n"})
    code, findings = check(capsys, root, "doc.md")
    assert code == 1
    assert values(findings, "path") == {"tools/biuld.py", "GUIDE.md"}
    assert all(f["line"] == 1 for f in findings)


# --- b. links -------------------------------------------------------------------------------------------------

def test_links_and_anchors_pass(tmp_path, capsys):
    root = make_repo(tmp_path, {
        "img.png": "",
        "docs/other.md": "# Title\n\n## Section Two: the `code`\n\n## Repeat\n\n## Repeat\n",
        "doc.md": ('<img src="img.png" alt="x">\n\n# Local heading\n\n'
                   "See [other](docs/other.md#section-two-the-code), [again](docs/other.md#repeat-1), "
                   "[here](#local-heading), [web](https://example.com/x.md#nope) and [mail](mailto:a@b.c).\n"),
    })
    assert check(capsys, root, "doc.md") == (0, [])


def test_links_flag_missing_targets_and_anchors(tmp_path, capsys):
    root = make_repo(tmp_path, {
        "docs/other.md": "# Title\n",
        "doc.md": ('<img src="gone.png">\n# Here\n'
                   "[a](docs/missing.md) [b](docs/other.md#no-such) [c](#nowhere)\n"),
    })
    code, findings = check(capsys, root, "doc.md")
    assert code == 1
    assert values(findings, "link") == {"gone.png", "docs/missing.md", "docs/other.md#no-such", "#nowhere"}


# --- c. commands ----------------------------------------------------------------------------------------------

COMMAND_FILES = {
    ".gitignore": "scripts/local.sh\n.venv/\n",
    "scripts/run.sh": "",
    "tools/gen.py": 'import os\nos.environ.get("FOO")\n',
    "pkg/__init__.py": "",
    "pkg/mod.py": "",
    "app/__main__.py": "",
    "req.txt": "",
}


def test_commands_pass_when_every_named_script_is_tracked(tmp_path, capsys):
    doc = ("```bash\n"
           "bash scripts/run.sh && .venv/bin/python -m pkg.mod   # comment naming scripts/local.sh\n"
           ".venv/bin/python tools/gen.py --flag \\\n"
           "  --out x; python3 -m app | tee log\n"
           "python -m pytest -q && .venv/bin/pip install -r req.txt\n"
           "FOO=1 ./scripts/run.sh\n"
           "```\n")
    root = make_repo(tmp_path, {**COMMAND_FILES, "doc.md": doc})
    assert check(capsys, root, "doc.md") == (0, [])


def test_commands_flag_missing_and_ignored_scripts(tmp_path, capsys):
    doc = ("```console\n"
           "$ bash scripts/missing.sh\n"
           "output that names scripts/not-a-command.sh\n"
           "$ python -m pkg.nope && pip install -r missing.txt\n"
           "$ bash scripts/local.sh\n"
           "```\n")
    root = make_repo(tmp_path, {**COMMAND_FILES, "doc.md": doc}, untracked={"scripts/local.sh": ""})
    code, findings = check(capsys, root, "doc.md")
    assert code == 1
    assert values(findings, "command") == {"scripts/missing.sh", "-m pkg.nope", "missing.txt", "scripts/local.sh"}
    ignored = next(f for f in findings if f["kind"] == "command" and f["value"] == "scripts/local.sh")
    assert "git-ignored" in str(ignored["detail"])
    # the same ignored file passes the path check: a local artefact is fine to mention, not to run
    assert "scripts/local.sh" not in values(findings, "path")


# --- enumeration is git ls-files, never the filesystem --------------------------------------------------------

def test_untracked_files_do_not_exist_and_are_not_scanned(tmp_path, capsys):
    doc = "```bash\nbash scripts/ghost.sh\npython helper.py\n```\nThe helper is helper.py.\n"
    root = make_repo(tmp_path, {"doc.md": doc}, untracked={
        "scripts/ghost.sh": "",                                # on disk, untracked, not ignored
        ".venv/lib/helper.py": "",
        ".venv/notes.md": "Broken: `tools/nowhere.py`.\n",
    })
    code, findings = check(capsys, root, "doc.md", ".venv/notes.md")
    assert code == 1
    assert values(findings, "command") == {"scripts/ghost.sh", "helper.py"}
    assert values(findings, "path") == {"scripts/ghost.sh", "helper.py"}   # the .venv basename does not count
    assert values(findings, "doc") == {".venv/notes.md"}
    assert not any(f["doc"] == ".venv/notes.md" and f["kind"] == "path" for f in findings)


# --- d. ports -------------------------------------------------------------------------------------------------

PORT_FILES = {
    ".gitignore": ".venv/\n",
    "scripts/verify-demo.sh": "PORT=${DEMO_PORT:-8599}\n",
    "relay/__init__.py": "",
    "relay/__main__.py": "",
    "relay/config.py": 'port=_number(env, "RELAY_PORT", 8787, minimum=1)\n',
    "script/fork.sh": "PORT=${FORK_PORT:-8547}\n",
    "dashboard/app.py": "",
}


def test_ports_match_the_code_defaults(tmp_path, capsys):
    doc = ("```bash\n"
           "streamlit run dashboard/app.py                  # http://localhost:8501\n"
           "streamlit run dashboard/app.py --server.port 9000  # http://localhost:9000\n"
           "DEMO_PORT=8599 bash scripts/verify-demo.sh\n"
           ".venv/bin/python -m relay                       # serve on 127.0.0.1:8787\n"
           "```\n"
           "| `RELAY_HOST`, `RELAY_PORT` | `127.0.0.1`, `8787` |\n"
           "The fork listens on localhost:8547; chain 42220 is not a port.\n")
    root = make_repo(tmp_path, {**PORT_FILES, "doc.md": doc})
    assert check(capsys, root, "doc.md") == (0, [])


def test_ports_flag_values_the_code_contradicts(tmp_path, capsys):
    doc = ("streamlit run dashboard/app.py  # http://localhost:8502\n"
           "DEMO_PORT=8600 bash scripts/verify-demo.sh\n"
           "python -m relay  # 127.0.0.1:8788\n"
           "| `RELAY_PORT` | `8789` |\n"
           "something else on localhost:1234\n")
    root = make_repo(tmp_path, {**PORT_FILES, "doc.md": doc})
    code, findings = check(capsys, root, "doc.md")
    assert code == 1
    ports = {(f["line"], f["value"]) for f in findings if f["kind"] == "port"}
    assert ports == {(1, "8502"), (2, "8600"), (3, "8788"), (4, "8789"), (5, "1234")}
    details = {f["value"]: str(f["detail"]) for f in findings}
    assert "8501" in details["8502"] and "8599" in details["8600"] and "8787" in details["8788"]


def test_streamlit_port_is_read_from_its_config(tmp_path, capsys):
    doc = "streamlit run dashboard/app.py  # http://localhost:8501\n"
    root = make_repo(tmp_path, {**PORT_FILES, ".streamlit/config.toml": "[server]\nport = 8600\n", "doc.md": doc})
    code, findings = check(capsys, root, "doc.md")
    assert code == 1 and values(findings, "port") == {"8501"}
    assert ".streamlit/config.toml" in str(findings[0]["detail"])


# --- e. env vars ----------------------------------------------------------------------------------------------

ENV_FILES = {
    "app.py": 'import os\nFOO = os.environ.get("FOO")\nKEY = ("KEYED",)\n',
    "run.sh": 'echo "$BAR" "${BAZ:-x}"\n',
    ".env.example": "FOO=\nTEMPLATE_ONLY=\n",
}


def test_env_vars_read_by_code_pass(tmp_path, capsys):
    doc = ("```bash\n"
           "export FOO=1\n"
           "BAR=2 bash run.sh   # NOT_A_VAR=3 in a comment\n"
           'OUT=$(cat app.py); echo "$OUT ${BAZ}"\n'
           "```\n"
           "Set the `KEYED` environment variable. The `VERIFIER_ROLE` secret and `DEFAULT_ADMIN_ROLE` are roles.\n"
           "`SOME_CONSTANT` is a Solidity constant, not configuration.\n")
    root = make_repo(tmp_path, {**ENV_FILES, "doc.md": doc})
    assert check(capsys, root, "doc.md") == (0, [])


def test_env_vars_no_code_reads_are_flagged(tmp_path, capsys):
    doc = ("```bash\n"
           "export NOPE=1\n"
           'echo "${NOPE2:-x}"\n'
           "```\n"
           "Set `GHOST` in `.env`. `TEMPLATE_ONLY` ships in the template.\n"
           "\n| Variable | Default |\n| --- | --- |\n| `TABLED` | 1 |\n")
    root = make_repo(tmp_path, {**ENV_FILES, "doc.md": doc})
    code, findings = check(capsys, root, "doc.md")
    assert code == 1
    assert values(findings, "env") == {"NOPE", "NOPE2", "GHOST", "TEMPLATE_ONLY", "TABLED"}


# --- f. submodules --------------------------------------------------------------------------------------------

GITMODULES = '[submodule "lib/dep"]\n\tpath = lib/dep\n\turl = https://example.com/dep\n'


def test_submodule_init_in_quick_start_passes(tmp_path, capsys):
    readme = "# X\n\n## Quick start\n\n```bash\ngit submodule update --init --recursive\nforge test\n```\n"
    root = make_repo(tmp_path, {".gitmodules": GITMODULES, "README.md": readme})
    assert check(capsys, root, "README.md") == (0, [])
    clone = "# X\n\n## Quick start\n\n```bash\ngit clone --recurse-submodules https://example.com/x\n```\n"
    (root / "README.md").write_text(clone)
    assert check(capsys, root, "README.md") == (0, [])


def test_missing_submodule_init_is_flagged(tmp_path, capsys):
    readme = ("# X\n\n## Quick start\n\n```bash\nforge test\n```\n"
              "\n## Other\n\n```bash\ngit submodule update --init\n```\n")
    root = make_repo(tmp_path, {".gitmodules": GITMODULES, "README.md": readme})
    code, findings = check(capsys, root, "README.md")
    assert code == 1
    assert [(f["kind"], f["line"]) for f in findings] == [("submodule", 5)]
    assert "lib/dep" in str(findings[0]["detail"])
    (root / ".gitmodules").unlink()
    subprocess.run(["git", "-C", str(root), "rm", "-q", "--cached", ".gitmodules"], check=True)
    assert check(capsys, root, "README.md") == (0, [])


# --- allowlist ------------------------------------------------------------------------------------------------

def write_allow(root: Path, entries: list[dict[str, str]]) -> str:
    (root / "allow.json").write_text(json.dumps({"entries": entries}))
    return "allow.json"


def test_allowlist_entry_without_reason_is_a_setup_error(tmp_path, capsys):
    root = make_repo(tmp_path, {"doc.md": "fine\n"})
    for entry in ({"kind": "path", "value": "x.py"}, {"kind": "path", "value": "x.py", "reason": "  "}):
        assert cdp.main(["--repo-root", str(root), "--docs", "doc.md", "--allow", write_allow(root, [entry])]) == 2
        assert "no reason" in capsys.readouterr().err


def test_allowlisted_finding_is_suppressed(tmp_path, capsys):
    root = make_repo(tmp_path, {"doc.md": "Uses web3.py and `GHOST` env var, and gone.md.\n"})
    allow = write_allow(root, [
        {"kind": "path", "value": "web3.py", "reason": "a library name"},
        {"kind": "env", "value": "GHOST", "doc": "doc.md", "reason": "user-supplied"},
        {"kind": "path", "value": "gone.md", "doc": "other.md", "reason": "scoped to another doc"},
    ])
    code, findings = check(capsys, root, "doc.md", allow=allow)
    assert code == 1
    assert [(f["kind"], f["value"]) for f in findings] == [("path", "gone.md")]


def test_unused_allowlist_entries_are_findings_on_the_default_set(tmp_path, capsys):
    tracked = {doc: "# Doc\n" for doc in cdp.DEFAULT_DOCS}
    tracked["docs/doc-path-allow.json"] = json.dumps({"entries": [
        {"kind": "path", "value": "stale.py", "reason": "no longer mentioned anywhere"}]})
    root = make_repo(tmp_path, tracked)
    code, findings = check(capsys, root)
    assert code == 1
    assert [(f["doc"], f["kind"], f["value"]) for f in findings] == [
        ("docs/doc-path-allow.json", "allowlist", "stale.py")]
    # with --docs the same entry is not judged: it may excuse a document outside the run
    assert check(capsys, root, "README.md") == (0, [])


def test_text_output_lists_documents_and_findings(tmp_path, capsys):
    root = make_repo(tmp_path, {"doc.md": "x\nsee `nope/file.py`\n"})
    assert cdp.main(["--repo-root", str(root), "--docs", "doc.md"]) == 1
    out = capsys.readouterr().out
    assert "checked 1 documents: doc.md" in out
    assert "doc.md:2: path: nope/file.py — " in out
