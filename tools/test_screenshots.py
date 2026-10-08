"""The committed Android renders must match their manifest, and the gate that says so must be able to fail.

Every negative control runs on a copy of mobile/android/screenshots in tmp_path, shown clean before it is broken.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools import check_screenshots as S

CLI = Path(S.__file__)


@pytest.fixture
def renders(tmp_path: Path) -> Path:
    d = tmp_path / "screenshots"
    shutil.copytree(S.DEFAULT_DIR, d)
    assert S.check(d) == []
    return d


def kinds(d: Path) -> list[str]:
    return [f["kind"] for f in S.check(d)]


def edit_manifest(d: Path, fn) -> None:
    m = json.loads((d / "manifest.json").read_text())
    fn(m)
    (d / "manifest.json").write_text(json.dumps(m))


def test_committed_renders_are_clean_and_complete():
    assert S.check(S.DEFAULT_DIR) == []
    m = json.loads((S.DEFAULT_DIR / "manifest.json").read_text())
    assert len(m["renders"]) == len(S.SCREENS) * len(S.MODES) == 12


def test_a_changed_png_is_a_digest_finding(renders):
    png = renders / "fix-dark.png"
    png.write_bytes(png.read_bytes() + b"\0")
    assert kinds(renders) == ["digest"]


def test_a_missing_pair_is_found(renders):
    edit_manifest(renders, lambda m: m.update(renders=[r for r in m["renders"] if r["path"] != "tree-light.png"]))
    assert sorted(kinds(renders)) == ["missing", "stray"]


def test_a_listed_file_not_on_disk_is_found(renders):
    (renders / "queue-light.png").unlink()
    assert kinds(renders) == ["absent"]


def test_a_duplicate_entry_is_found(renders):
    edit_manifest(renders, lambda m: m["renders"].append(dict(m["renders"][0])))
    assert kinds(renders) == ["missing"]


def test_a_path_outside_the_directory_is_refused(renders):
    def escape(m):
        m["renders"][0]["path"] = "../setup-light.png"
    edit_manifest(renders, escape)
    assert sorted(kinds(renders)) == ["manifest", "stray"]


def test_cli_exit_codes(renders, tmp_path):
    def run(*a):
        return subprocess.run([sys.executable, str(CLI), *a], capture_output=True, text=True, timeout=60)
    assert run("--dir", str(renders)).returncode == 0
    (renders / "photos-light.png").write_bytes(b"not a png")
    bad = run("--dir", str(renders))
    assert bad.returncode == 1 and "photos-light.png" in bad.stdout
    assert run("--dir", str(tmp_path / "nowhere")).returncode == 2
