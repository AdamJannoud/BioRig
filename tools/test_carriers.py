"""The proposal carriers in the workspace Files must still be what their repo source produces, and the gate that says
so must be able to fail.

The negative controls run against a small tree in tmp_path: the markdown, both renderers, the stylesheet, the
lockup and the diagram svg copied from the checkout, plus a stand-in raster of a few bytes (the real one is 1.8 MB
and the gate only hashes it). The tree is recorded once per module from its own fresh renders, and each test gets
its own copy, shown to pass before it is broken, so a red result cannot be a broken copy. Renders are memoised on
their inputs, so only a test that changes an input pays for a new one. One control runs the real CLI on this
checkout against the committed record: with nothing staged it must pass in any environment, noting that the pdf's
raw bytes are not attested there, because Chromium print-to-PDF bytes depend on the browser build and fonts. The
controls below show that byte comparison is still enforced wherever the published copies are staged. Nothing here
reads cache/carriers/published/.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from tools import check_carriers as C

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "tools" / "check_carriers.py"
COPIED = (C.MARKDOWN, C.PDF_RENDERER, C.DOCX_RENDERER, C.STYLESHEET, C.LOCKUP, C.DIAGRAM_SVG)
STAND_IN_RASTER = b"\x89PNG\r\n\x1a\n stand-in raster for the carrier gate tests\n"

_real_render = C.render
_renders: dict[str, bytes] = {}


def memo_render(root: Path, carrier: C.Carrier, out_dir: Path) -> Path:
    """C.render, keyed on the bytes of every input the renderer reads."""
    if not (root / carrier.renderer).exists():
        return _real_render(root, carrier, out_dir)
    key = carrier.name + "".join(C.sha256_file(root / rel) for rel in carrier.sources)
    out = out_dir / carrier.name
    if key not in _renders:
        _renders[key] = _real_render(root, carrier, out_dir).read_bytes()
    out.write_bytes(_renders[key])
    return out


@pytest.fixture(autouse=True)
def memoised(monkeypatch):
    monkeypatch.setattr(C, "render", memo_render)


def run(root: Path, *args: str, staged: Path | None = None) -> int:
    return C.main(["--root", str(root), "--staged", str(staged or root / C.STAGED), *args])


@pytest.fixture(scope="module")
def recorded(tmp_path_factory) -> Path:
    """A fixture tree whose staged copies are its own fresh renders, recorded with --record."""
    root = tmp_path_factory.mktemp("carriers")
    for rel in COPIED:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, root / rel)
    (root / C.RASTER).write_bytes(STAND_IN_RASTER)
    staged = root / C.STAGED
    staged.mkdir(parents=True)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(C, "render", memo_render)
        for carrier in C.CARRIERS:
            if carrier.renderer:
                memo_render(root, carrier, staged)
            else:
                shutil.copyfile(root / carrier.copy_of, staged / carrier.name)
        assert run(root, "--record") == 0
    return root


@pytest.fixture
def tree(recorded, tmp_path, capsys) -> Path:
    root = tmp_path / "tree"
    shutil.copytree(recorded, root)
    assert run(root) == 0  # the copy passes before it is broken
    capsys.readouterr()
    return root


def drift(capsys) -> list[str]:
    return [line for line in capsys.readouterr().err.splitlines() if line.startswith("drift: ")]


# ---- the committed record describes this checkout

def test_committed_record_matches_the_tree(tmp_path):
    """Control 1: the real CLI, real renders, on this checkout, with nothing staged: the CI shape. Every source
    digest is asserted; the pdf's render bytes are noted as unattested here, whatever they came out as."""
    run_ = subprocess.run([sys.executable, str(CLI), "--staged", str(tmp_path / "none")],
                          capture_output=True, text=True, timeout=600)
    assert (run_.returncode, run_.stderr) == (0, "")
    out = run_.stdout.splitlines()
    assert any(l.startswith("note: no staged copies in") for l in out)
    assert any(l.startswith("note: proposal.pdf: a fresh render ") and "not attested in this environment" in l
               and l.endswith("the recorded source digests are enforced") for l in out)
    for carrier in C.CARRIERS:
        n = len(carrier.sources)
        assert f"ok: {carrier.name}: {n}/{n} sources match the record" in out
    for name in ("proposal.docx", "proposal.md", "architecture.png"):
        assert any(l.startswith(f"ok: {name}: ") and "matches the published" in l for l in out)
    assert [l for l in out if not l.startswith("ok: ")] == [l for l in out if l.startswith("note: ")]
    assert sum(l.startswith("note: ") for l in out) == 2


def test_committed_record_covers_every_source_and_no_internal_location():
    raw = (ROOT / C.RECORD).read_text()
    record = C.load_record(ROOT)
    assert sorted(record) == sorted(c.name for c in C.CARRIERS)
    for carrier in C.CARRIERS:
        assert sorted(record[carrier.name]["sources"]) == sorted(rel.as_posix() for rel in carrier.sources)
        assert record[carrier.name]["algorithm"] == carrier.algorithm
    assert raw == C.render_record(list(json.loads(raw)["carriers"]))  # deterministic layout, trailing newline
    assert json.loads(raw)["location"] == C.LOCATION
    for leak in ("/mnt/", "/files/", "chat_", "bucket"):
        assert leak not in raw


# ---- the normalized docx digest

def _zip(path: Path, stamp: tuple, parts: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(zipfile.ZipInfo(name, date_time=stamp), data)
    return path


def test_zip_digest_ignores_entry_timestamps_and_nothing_else(tmp_path):
    parts = {"word/document.xml": b"<w:document/>", "[Content_Types].xml": b"<Types/>"}
    a = _zip(tmp_path / "a.docx", (2026, 10, 2, 18, 6, 0), parts)
    b = _zip(tmp_path / "b.docx", (2026, 10, 2, 18, 6, 4), parts)
    assert a.read_bytes() != b.read_bytes()
    assert C.zip_entries_digest(a) == C.zip_entries_digest(b)
    c = _zip(tmp_path / "c.docx", (2026, 10, 2, 18, 6, 0), {**parts, "word/document.xml": b"<w:document x='1'/>"})
    assert C.zip_entries_digest(c) != C.zip_entries_digest(a)
    expected = hashlib.sha256(b"".join(
        f"{i.filename}\0{i.CRC:08x}\0{i.file_size}\n".encode()
        for i in sorted(zipfile.ZipFile(a).infolist(), key=lambda i: i.filename))).hexdigest()
    assert C.zip_entries_digest(a) == expected


# ---- perturbations

def test_clean_tree_passes(tree, capsys):
    assert run(tree) == 0
    out = capsys.readouterr()
    assert out.err == ""
    assert sum(line.startswith("ok: ") for line in out.out.splitlines()) == 3 * len(C.CARRIERS)


def test_edited_markdown_is_caught_on_every_carrier_it_feeds(tree, capsys):
    with (tree / C.MARKDOWN).open("a") as f:
        f.write("\nA sentence added after the carriers were published.\n")
    assert run(tree) == 1
    lines = drift(capsys)
    for name in ("proposal.pdf", "proposal.docx", "proposal.md"):
        assert any(line.startswith(f"drift: {name}: source docs/prezenti-proposal.md moved") for line in lines)
    assert any(l.startswith("drift: proposal.pdf: a fresh render is sha256 ") for l in lines)
    assert any(l.startswith("drift: proposal.docx: a fresh render is sha256-zip-entries ") for l in lines)
    assert not any("architecture.png" in line for line in lines)
    assert all("--record (DEPLOY.md section 9)" in line for line in lines if " moved " in line)


def test_edited_renderer_is_caught(tree, capsys):
    with (tree / C.PDF_RENDERER).open("a") as f:
        f.write("\n# a renderer change nothing republished\n")
    assert run(tree) == 1
    lines = drift(capsys)
    assert len(lines) == 1, lines  # the output is unchanged, so only the source check sees it
    assert lines[0].startswith("drift: proposal.pdf: source tools/render_proposal_pdf.py moved (recorded ")
    assert lines[0].endswith("then --record (DEPLOY.md section 9)")


def test_altered_raster_is_caught(tree, capsys):
    (tree / C.RASTER).write_bytes(STAND_IN_RASTER + b"regenerated")
    assert run(tree) == 1
    lines = drift(capsys)
    assert any(l.startswith("drift: architecture.png: source BioRig_Architecture_Pro.png moved") for l in lines)
    assert any(l.startswith("drift: architecture.png: the committed BioRig_Architecture_Pro.png is sha256 ")
               for l in lines)


def test_staged_copy_differing_is_caught(tree, capsys):
    """The stale diagram raster of 2 October: the repo is clean, the copy in Files is not."""
    (tree / C.STAGED / "architecture.png").write_bytes(b"a pre-brand copy")
    assert run(tree) == 1
    assert drift(capsys) == [
        "drift: architecture.png: the copy in cache/carriers/published/architecture.png is not the published "
        f"artifact (sha256 {C.sha256_file(tree / C.STAGED / 'architecture.png')[:12]}, record "
        f"{C.sha256_file(tree / C.RASTER)[:12]})"]


def test_absent_staged_dir_passes_with_a_note(tree, capsys):
    shutil.rmtree(tree / C.STAGED)
    assert run(tree) == 0
    out = capsys.readouterr()
    assert out.err == ""
    assert "note: no staged copies in cache/carriers/published/; download the four carriers" in out.out
    assert "note: proposal.pdf: a fresh render matches the published sha256 " in out.out
    assert "not attested in this environment" in out.out


def foreign_render(monkeypatch):
    """Renders as a machine without the pinned browser build or brand fonts would: same source, other pdf bytes."""
    def render(root: Path, carrier: C.Carrier, out_dir: Path) -> Path:
        out = memo_render(root, carrier, out_dir)
        if carrier.name == "proposal.pdf":
            out.write_bytes(out.read_bytes() + b"\n% rendered with other fonts\n")
        return out
    monkeypatch.setattr(C, "render", render)


def test_foreign_render_without_staged_copies_is_a_note(tree, capsys, monkeypatch):
    """The CI failure of run 37072253803: unchanged source, other render bytes, nothing staged. Not drift."""
    shutil.rmtree(tree / C.STAGED)
    foreign_render(monkeypatch)
    assert run(tree) == 0
    out = capsys.readouterr()
    assert out.err == ""
    note = [l for l in out.out.splitlines() if l.startswith("note: proposal.pdf: ")]
    assert len(note) == 1 and note[0].startswith("note: proposal.pdf: a fresh render is ")
    assert ", not the published sha256 " in note[0] and "not attested in this environment" in note[0]
    assert "ok: proposal.pdf: 4/4 sources match the record" in out.out


def test_foreign_render_with_staged_copies_is_drift(tree, capsys, monkeypatch):
    """Where the published copies are staged the byte comparison is still asserted, exactly as before."""
    foreign_render(monkeypatch)
    assert run(tree) == 1
    lines = drift(capsys)
    assert len(lines) == 1, lines
    assert lines[0].startswith("drift: proposal.pdf: a fresh render is sha256 ")
    assert lines[0].endswith("then --record (DEPLOY.md section 9)")


def test_staged_pdf_differing_is_caught(tree, capsys):
    (tree / C.STAGED / "proposal.pdf").write_bytes(b"%PDF-1.7 an older render")
    assert run(tree) == 1
    lines = drift(capsys)
    assert len(lines) == 1, lines
    assert lines[0].startswith("drift: proposal.pdf: the copy in cache/carriers/published/proposal.pdf is not the "
                               "published artifact (sha256 ")


def test_staged_pdf_alone_turns_the_byte_comparison_on(tree, capsys, monkeypatch):
    for name in ("proposal.docx", "proposal.md", "architecture.png"):
        (tree / C.STAGED / name).unlink()
    foreign_render(monkeypatch)
    assert run(tree) == 1
    assert [l.split(" is ")[0] for l in drift(capsys)] == ["drift: proposal.pdf: a fresh render"]


def test_edited_record_digest_is_caught(tree, capsys):
    path = tree / C.RECORD
    raw = json.loads(path.read_text())
    pdf = next(c for c in raw["carriers"] if c["name"] == "proposal.pdf")
    pdf["digest"] = "0" * 64
    path.write_text(C.render_record(raw["carriers"]))
    assert run(tree) == 1
    lines = drift(capsys)
    assert any(l.startswith("drift: proposal.pdf: a fresh render is sha256 ") for l in lines)
    assert any(l.startswith("drift: proposal.pdf: the copy in cache/carriers/published/proposal.pdf") for l in lines)


def test_edited_record_source_is_caught_without_staged_copies(tree, capsys):
    shutil.rmtree(tree / C.STAGED)
    path = tree / C.RECORD
    raw = json.loads(path.read_text())
    pdf = next(c for c in raw["carriers"] if c["name"] == "proposal.pdf")
    pdf["sources"][C.STYLESHEET.as_posix()] = "0" * 64
    path.write_text(C.render_record(raw["carriers"]))
    assert run(tree) == 1
    lines = drift(capsys)
    assert len(lines) == 1, lines
    assert lines[0].startswith("drift: proposal.pdf: source tools/print/proposal.css moved (recorded 000000000000, ")


def test_edited_markdown_without_staged_copies_is_caught(tree, capsys):
    shutil.rmtree(tree / C.STAGED)
    with (tree / C.MARKDOWN).open("a") as f:
        f.write("\nA sentence added after the carriers were published.\n")
    assert run(tree) == 1
    lines = drift(capsys)
    for name in ("proposal.pdf", "proposal.docx", "proposal.md"):
        assert any(l.startswith(f"drift: {name}: source docs/prezenti-proposal.md moved") for l in lines)
    assert any(l.startswith("drift: proposal.docx: a fresh render is sha256-zip-entries ") for l in lines)


def test_absent_staged_dir_still_fails_on_repo_drift(tree, capsys):
    shutil.rmtree(tree / C.STAGED)
    (tree / C.DIAGRAM_SVG).write_text("<svg/>")
    assert run(tree) == 1
    assert drift(capsys)[0].startswith("drift: architecture.png: source assets/BioRig_Architecture_v5.svg moved")


def test_missing_record_is_a_setup_failure(tree, capsys):
    (tree / C.RECORD).unlink()
    assert run(tree) == 2
    assert capsys.readouterr().err.startswith("setup: docs/carriers.json missing")


def test_missing_renderer_is_a_setup_failure(tree, capsys):
    (tree / C.DOCX_RENDERER).unlink()
    assert run(tree) == 2
    assert "setup: renderer tools/render_proposal_docx.py missing" in capsys.readouterr().err


def test_record_refuses_a_mismatched_staged_copy(tree, capsys):
    before = (tree / C.RECORD).read_bytes()
    (tree / C.STAGED / "proposal.pdf").write_bytes(b"%PDF-1.7 an older render")
    assert run(tree, "--record") == 1
    lines = drift(capsys)
    assert len(lines) == 1 and lines[0].startswith("drift: proposal.pdf: refusing to record: the copy in proposal.pdf")
    assert (tree / C.RECORD).read_bytes() == before


def test_record_on_an_agreeing_tree_is_byte_identical(tree):
    before = (tree / C.RECORD).read_bytes()
    assert run(tree, "--record") == 0
    assert (tree / C.RECORD).read_bytes() == before


def test_json_report(tree, capsys):
    (tree / C.STAGED / "proposal.md").write_text("an older copy\n")
    assert run(tree, "--json") == 1
    report = json.loads(capsys.readouterr().out)
    assert (report["status"], report["exit"], report["staged"]) == ("drift", 1, True)
    bad = [c for c in report["checks"] if c["status"] == "drift"]
    assert [(c["carrier"], c["check"]) for c in bad] == [("proposal.md", "staged")]


# ---- --require-staged: the publish-flow shape (closing gate of DEPLOY.md section 9)

def test_require_staged_with_nothing_staged_is_drift(tree, capsys):
    shutil.rmtree(tree / C.STAGED)
    assert run(tree, "--require-staged") == 1
    lines = drift(capsys)
    assert any(l.startswith("drift: no staged copies in cache/carriers/published/") for l in lines)
    assert any(l.startswith("drift: proposal.pdf: a fresh render ") and "--require-staged" in l for l in lines)


def test_require_staged_partial_staging_is_drift_on_that_carrier(tree, capsys):
    (tree / C.STAGED / "architecture.png").unlink()
    assert run(tree, "--require-staged") == 1
    lines = drift(capsys)
    assert any(l.startswith("drift: architecture.png: not staged in cache/carriers/published/") for l in lines)
    # the pdf is still staged, so its render bytes are attested and match: it is not part of the drift
    assert not any(l.startswith("drift: proposal.pdf: a fresh render ") for l in lines)


def test_require_staged_with_everything_staged_passes(tree, capsys):
    assert run(tree, "--require-staged") == 0
    out = capsys.readouterr()
    assert out.err == ""
    assert all(l.startswith("ok: ") for l in out.out.splitlines())


def test_require_staged_unattested_render_is_a_note_without_the_flag(tree, capsys, monkeypatch):
    """Same state, two verdicts: the plain check notes the unattested pdf, --require-staged drifts on it."""
    shutil.rmtree(tree / C.STAGED)
    foreign_render(monkeypatch)
    assert run(tree) == 0
    assert run(tree, "--require-staged") == 1
    lines = drift(capsys)
    assert any(l.startswith("drift: proposal.pdf: a fresh render ") and "--require-staged" in l for l in lines)


def test_require_staged_with_staged_mismatch_still_fails(tree, capsys):
    (tree / C.STAGED / "proposal.pdf").write_bytes(b"%PDF-1.7 an older render")
    assert run(tree, "--require-staged") == 1
    lines = drift(capsys)
    assert len(lines) == 1 and lines[0].startswith(
        "drift: proposal.pdf: the copy in cache/carriers/published/proposal.pdf is not the published artifact (")


def test_require_staged_mutually_exclusive_with_record(tree, capsys):
    with pytest.raises(SystemExit) as exc:
        run(tree, "--require-staged", "--record")
    assert exc.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


def test_require_staged_json_report_is_drift(tree, capsys):
    shutil.rmtree(tree / C.STAGED)
    assert run(tree, "--require-staged", "--json") == 1
    report = json.loads(capsys.readouterr().out)
    assert (report["status"], report["exit"], report["staged"]) == ("drift", 1, False)
    assert any(c["status"] == "drift" and c["check"] == "staged" for c in report["checks"])
    assert any(c["status"] == "drift" and c["carrier"] == "proposal.pdf" for c in report["checks"])
