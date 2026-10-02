"""The clean-clone proof's parsing and verdict logic, offline: the quick start fence, the key redaction and the gate
transcript. The proof itself (a clone, an install, the whole gate) is too heavy for a unit test; this pins the parts
that decide what it runs and what it reports, above all that a skipped step can never read as a pass."""

from __future__ import annotations

import pytest

from tools import clean_clone_proof as ccp

README = """# X

## Quick start

```bash
export PRIVATE_KEY=<verifier key>        # comment
git submodule update --init
forge test \\
  -vv
# a comment-only line
bash scripts/verify-demo.sh
```

## Next
"""


def test_quick_start_lines_are_parsed_in_order(tmp_path):
    (tmp_path / "README.md").write_text(README)
    lines = ccp.quick_start_lines(tmp_path / "README.md")
    assert lines[0].startswith("export PRIVATE_KEY=<verifier key>")
    assert lines[1:] == ["git submodule update --init", "forge test    -vv", "bash scripts/verify-demo.sh"]


@pytest.mark.parametrize("text, why", [
    ("# X\n\nno section\n", "no '## Quick start'"),
    ("## Quick start\n\nprose only\n\n## Next\n```bash\nls\n```\n", "no ```bash fence"),
    ("## Quick start\n\n```bash\nls\n", "never closed"),
    ("## Quick start\n\n```bash\n# only a comment\n```\n", "no commands"),
])
def test_a_missing_or_broken_fence_is_an_error_not_a_skip(tmp_path, text, why):
    (tmp_path / "README.md").write_text(text)
    with pytest.raises(ValueError, match=why):
        ccp.quick_start_lines(tmp_path / "README.md")


def test_the_key_placeholder_is_redacted_in_what_is_shown():
    assert ccp.display("export PRIVATE_KEY=<verifier key>  # x") == "export PRIVATE_KEY=<redacted>  # x"
    assert ccp.GATE_RE.search("bash scripts/verify-demo.sh   # the full acceptance check")
    assert ccp.SERVER_RE.search(".venv/bin/streamlit run dashboard/app.py")


def test_runner_output_redacts_the_key(tmp_path):
    key = "ab" * 32
    r = ccp.Runner(tmp_path, key, tmp_path)
    assert key not in r._redact(f"value {key.upper()} and 0x{key}")


def test_runner_carries_exports_and_cwd_between_lines(tmp_path):
    (tmp_path / "sub").mkdir()
    r = ccp.Runner(tmp_path, None, tmp_path)
    assert r.shell("export FOO=bar && cd sub")[0] == 0
    rc, out = r.shell('echo "$FOO $(basename "$PWD")"')
    assert rc == 0 and out[-1] == "bar sub"
    assert r.shell("false")[0] == 1


def test_a_key_free_gate_transcript_is_partial_not_passed():
    out = ["== 1. a", "== 3. live", "SKIPPED (no key): step 3", "== 4b. fork", "SKIPPED (no key): step 4b",
           "", "PARTIAL: DEMO CHECKS PASSED EXCEPT SKIPPED STEPS: 3 4b (key-free mode, not a full acceptance pass)"]
    g = ccp.parse_gate(out, 0)
    assert g["skipped_steps"] == ["3", "4b"] and not g["full_banner"] and g["failing_step"] is None
    full = ccp.parse_gate(["== 1. a", "", ccp.FULL_BANNER], 0)
    assert full["full_banner"] and not full["skipped_steps"]
    red = ccp.parse_gate(["== 1. a", "== 2. unit tests", "boom"], 1)
    assert red["failing_step"] == "2. unit tests"


def test_nested_proofs_are_refused(monkeypatch):
    monkeypatch.setenv("CLEAN_CLONE_PROOF", "1")
    assert ccp.main(["--source", "local", "--no-key"]) == 2
