"""The published carriers in the workspace Files must still be what their repo source produces, and the gate that says
so must be able to fail.

The negative controls run against a small tree in tmp_path: the proposal and report markdown, the three renderers, the
stylesheet, the lockup, the deployment plan and FINDINGS.md, a stand-in diagram svg, a stand-in raster of a few bytes (the real one is 1.8 MB and the gate only hashes it), a
small stand-in slide raster carrying the same tEXt provenance the generator writes, a stand-in app source under
mobile/android in a git repo, and a stand-in apk (a zip with the two entries that make one). The tree is recorded once
per module from its own fresh renders, and each test gets its own copy, shown to pass before it is broken, so a red
result cannot be a broken copy. Renders are memoised on their inputs, so only a test that changes an input pays for a
new one. One control runs the real CLI on this checkout against the committed record: with nothing staged it must pass
in any environment, noting that the pdf's raw render bytes and the slide raster's provenance are not attested there,
because Chromium print-to-PDF bytes depend on the browser build and fonts, and the raster's provenance is only read
where its published copy is staged. The controls below show that byte comparison is still enforced wherever the
published copies are staged. Nothing here reads cache/carriers/published/.
"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from tools import check_carriers as C

if C.diagram is None:  # the provenance keys live in the generator, which needs Pillow to import
    pytest.skip(f"the diagram generator's provenance keys are not importable: {C.DIAGRAM_IMPORT_ERROR}",
                allow_module_level=True)

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "tools" / "check_carriers.py"
COPIED = (C.MARKDOWN, C.PDF_RENDERER, C.DOCX_RENDERER, C.STYLESHEET, C.LOCKUP, C.ARCH_GENERATOR,
          C.REPORT_MARKDOWN, C.REPORT_RENDERER, C.DEPLOYMENT_PLAN, C.FINDINGS)
STAND_IN_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="8" height="5" viewBox="0 0 8 5">'
                '<rect width="8" height="5" fill="#ffffff"/></svg>')
STAND_IN_RASTER = b"\x89PNG\r\n\x1a\n stand-in raster for the carrier gate tests\n"
STAND_IN_APP = ("app/src/main/kotlin/org/biorig/app/MainActivity.kt", "core/build.gradle.kts")

_real_render = C.render
_renders: dict[str, bytes] = {}


def stand_in_apk(path: Path) -> Path:
    """The two entries the gate's package check reads: without either, the file is not an Android package."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("AndroidManifest.xml", b"<manifest package='org.biorig.app'/>")
        z.writestr("classes.dex", b"dex\n035\x00 stand-in")
    return path


def slide_raster(svg: str, *, size: tuple[int, int] | None = None, svg_sha: str | None = None,
                 generator: str | None = None, pixels: bytes | None = None, provenance: bool = True) -> bytes:
    """A PNG carrying the provenance the diagram generator stamps into every raster it paints, over stand-in pixels."""
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo

    want = size or C.svg_declared_size(svg)
    assert want, "the stand-in svg must declare a pixel size"
    info = None
    if provenance:
        info = PngInfo()
        info.add_text(C.diagram.PNG_SVG_SHA_KEY, svg_sha or hashlib.sha256(svg.encode()).hexdigest())
        info.add_text(C.diagram.PNG_GENERATOR_KEY, C.diagram.GENERATOR if generator is None else generator)
    data = pixels or bytes((i * 7 + 3) % 256 for i in range(want[0] * want[1] * 3))
    with io.BytesIO() as buf:
        Image.frombytes("RGB", want, data).save(buf, format="PNG", pnginfo=info)
        return buf.getvalue()


def flip(raw: bytes, offset: int) -> bytes:
    """One byte, one bit: the tamper the gate has to catch."""
    return raw[:offset] + bytes([raw[offset] ^ 0x01]) + raw[offset + 1:]


def commit(root: Path, message: str) -> None:
    """Commit the tree, so the app source has a git tree the record can pin. Config comes from the command line, so
    the suite does not depend on a user's git identity."""
    identity = ("-c", "user.name=carrier tests", "-c", "user.email=tests@example.invalid")
    if not (root / ".git").exists():
        subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), *identity, "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), *identity, "commit", "-q", "-m", message], check=True, capture_output=True)


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
    (root / C.DIAGRAM_SVG).parent.mkdir(parents=True, exist_ok=True)
    (root / C.DIAGRAM_SVG).write_text(STAND_IN_SVG)
    (root / C.RASTER).write_bytes(STAND_IN_RASTER)
    for rel in STAND_IN_APP:
        (root / C.APP_SOURCE / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / C.APP_SOURCE / rel).write_text(f"// stand-in app source: {rel}\n")
    commit(root, "the stand-in tree the carriers are recorded against")
    staged = root / C.STAGED
    staged.mkdir(parents=True)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(C, "render", memo_render)
        for carrier in C.CARRIERS:
            if carrier.renderer:
                memo_render(root, carrier, staged)
            elif carrier.copy_of:
                shutil.copyfile(root / carrier.copy_of, staged / carrier.name)
            elif carrier.provenance_of:
                (staged / carrier.name).write_bytes(slide_raster((root / carrier.provenance_of).read_text()))
            else:
                stand_in_apk(staged / carrier.name)
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
    digest is asserted; the pdf's render bytes and the slide raster's provenance are noted as unattested here,
    whatever they came out as."""
    run_ = subprocess.run([sys.executable, str(CLI), "--staged", str(tmp_path / "none")],
                          capture_output=True, text=True, timeout=600)
    assert (run_.returncode, run_.stderr) == (0, "")
    out = run_.stdout.splitlines()
    assert any(l.startswith("note: no staged copies in") for l in out)
    assert any(l.startswith("note: proposal.pdf: a fresh render ") and "not attested in this environment" in l
               and l.endswith("the recorded source digests are enforced") for l in out)
    note = f"note: {C.SLIDE_PNG}: the published raster's provenance is not checked here"
    assert any(l.startswith(note) for l in out)
    for carrier in C.CARRIERS:
        n = len(carrier.sources)
        if n:
            assert f"ok: {carrier.name}: {n}/{n} sources match the record" in out
    for name in ("proposal.docx", "proposal.md", "architecture.png", "architecture.svg", "milestone-report.docx",
                 "celo-mainnet-deployment-plan.md", "findings.md"):
        assert any(l.startswith(f"ok: {name}: ") and "matches the published" in l for l in out)
    assert any(l.startswith(f"ok: {C.APK}: the app source mobile/android is the tree ") for l in out)
    assert [l for l in out if not l.startswith("ok: ")] == [l for l in out if l.startswith("note: ")]
    assert sum(l.startswith("note: ") for l in out) == 3


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
    # every carrier gets a derivation and a staged line; only the ones with file sources get a source line
    expected = sum(1 for carrier in C.CARRIERS if carrier.sources) + 2 * len(C.CARRIERS)
    assert sum(line.startswith("ok: ") for line in out.out.splitlines()) == expected


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
    assert "note: no staged copies in cache/carriers/published/; download the published carriers" in out.out
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


# ---- the svg copy, the slide raster and the apk: one flipped byte each, and how each is tied to its source

def test_flipped_byte_in_the_staged_vector_copy_is_caught(tree, capsys):
    path = tree / C.STAGED / "architecture.svg"
    raw = path.read_bytes()
    path.write_bytes(flip(raw, len(raw) // 2))
    assert run(tree) == 1
    lines = drift(capsys)
    assert len(lines) == 1, lines
    assert lines[0].startswith("drift: architecture.svg: the copy in cache/carriers/published/architecture.svg is not "
                               "the published artifact (sha256 ")


def test_flipped_byte_in_the_staged_apk_is_caught(tree, capsys):
    path = tree / C.STAGED / C.APK
    raw = path.read_bytes()
    path.write_bytes(flip(raw, len(raw) // 2))
    assert run(tree) == 1
    lines = drift(capsys)
    assert len(lines) == 1, lines
    assert lines[0].startswith(f"drift: {C.APK}: the copy in cache/carriers/published/{C.APK} is not the published "
                               "artifact (sha256 ")


def test_flipped_pixel_in_the_staged_slide_raster_is_caught(tree, capsys):
    """Its pixels are never compared at gate time, so the staged byte check is what catches a repainted copy: same
    size, intact provenance, other pixels."""
    (tree / C.STAGED / C.SLIDE_PNG).write_bytes(slide_raster(STAND_IN_SVG, pixels=bytes(8 * 5 * 3)))
    assert run(tree) == 1
    lines = drift(capsys)
    assert len(lines) == 1, lines
    assert lines[0].startswith(f"drift: {C.SLIDE_PNG}: the copy in cache/carriers/published/{C.SLIDE_PNG} is not the "
                               "published artifact (sha256 ")


def test_slide_raster_naming_other_svg_bytes_is_caught(tree, capsys):
    """The provenance read alone fails on a raster repainted from other vector bytes: it names the bytes it came from,
    and that name is the committed svg's digest only for a genuine render of the committed svg."""
    (tree / C.STAGED / C.SLIDE_PNG).write_bytes(slide_raster(STAND_IN_SVG, svg_sha="0" * 64))
    assert run(tree) == 1
    lines = drift(capsys)
    assert any(l.startswith(f"drift: {C.SLIDE_PNG}: the staged {C.SLIDE_PNG} was rendered from other svg bytes: its "
                            f"{C.diagram.PNG_SVG_SHA_KEY} chunk is 0000") for l in lines)


def test_slide_raster_of_another_size_is_caught(tree, capsys):
    (tree / C.STAGED / C.SLIDE_PNG).write_bytes(slide_raster(STAND_IN_SVG, size=(4, 3)))
    assert run(tree) == 1
    lines = drift(capsys)
    assert any(l.startswith(f"drift: {C.SLIDE_PNG}: the staged {C.SLIDE_PNG} is 4x3 px, the vector source declares "
                            f"8x5; ") for l in lines)


def test_slide_raster_without_provenance_is_caught(tree, capsys):
    """What a raster from anything but the generator looks like: the declared size, no tEXt provenance at all."""
    (tree / C.STAGED / C.SLIDE_PNG).write_bytes(slide_raster(STAND_IN_SVG, provenance=False))
    assert run(tree) == 1
    lines = drift(capsys)
    assert any(l.startswith(f"drift: {C.SLIDE_PNG}: the staged {C.SLIDE_PNG} was rendered from other svg bytes: its "
                            f"{C.diagram.PNG_SVG_SHA_KEY} chunk is absent") for l in lines)


def test_slide_raster_not_staged_is_a_note_and_drift_under_require_staged(tree, capsys):
    (tree / C.STAGED / C.SLIDE_PNG).unlink()
    assert run(tree) == 0
    assert capsys.readouterr().err == ""
    assert run(tree, "--require-staged") == 1
    lines = drift(capsys)
    assert any(l.startswith(f"drift: {C.SLIDE_PNG}: the published raster's provenance is not checked here") for l in lines)


def test_edited_svg_is_caught_on_every_carrier_it_feeds(tree, capsys):
    """One added byte in the committed vector source reaches the svg copy, the committed raster and the slide raster."""
    with (tree / C.DIAGRAM_SVG).open("a") as f:
        f.write("<!-- one byte more -->\n")
    assert run(tree) == 1
    lines = drift(capsys)
    for name in ("architecture.png", "architecture.svg", C.SLIDE_PNG):
        assert any(l.startswith(f"drift: {name}: source assets/BioRig_Architecture_v5.svg moved") for l in lines)
    assert any(l.startswith(f"drift: {C.SLIDE_PNG}: the staged {C.SLIDE_PNG} was rendered from other svg bytes")
               for l in lines)


def test_edited_app_source_is_caught(tree, capsys):
    """A file added under mobile/android and never committed: the apk is no longer from this app source, and the tree
    hash alone would not see it, so the check reads untracked files too."""
    added = tree / C.APP_SOURCE / "app" / "src" / "NewScreen.kt"
    added.parent.mkdir(parents=True, exist_ok=True)
    added.write_text("// a screen added after the apk was published\n")
    assert run(tree) == 1
    lines = drift(capsys)
    assert len(lines) == 1, lines
    assert lines[0].startswith(f"drift: {C.APK}: the app source mobile/android has moved past the tree ")
    assert "mobile/android/app/src/NewScreen.kt" in lines[0]
    assert lines[0].endswith("--record (DEPLOY.md section 9)")


def test_committed_app_source_move_is_caught(tree, capsys):
    """The other half: a change committed in the app source, with nothing rebuilt, moves HEAD's tree off the pin."""
    moved = tree / C.APP_SOURCE / STAND_IN_APP[0]
    moved.write_text(moved.read_text() + "// one line more\n")
    commit(tree, "app: a change committed after the apk was published")
    assert run(tree) == 1
    lines = drift(capsys)
    assert len(lines) == 1, lines
    assert lines[0].startswith(f"drift: {C.APK}: the app source mobile/android has moved past the tree ")
    assert f"mobile/android/{STAND_IN_APP[0]}" in lines[0]


def test_record_pins_the_app_tree_it_recorded_against(tree, capsys):
    assert run(tree, "--record") == 0
    assert C.load_record(tree)[C.APK]["build_source"] == {
        "path": C.APP_SOURCE.as_posix(), "tree": C.app_source_tree(tree, C.APP_SOURCE)}


def test_record_refuses_a_staged_file_that_is_not_an_android_package(tree, capsys):
    _zip(tree / C.STAGED / C.APK, (2026, 10, 3, 12, 0, 0), {"docProps/core.xml": b"<x/>"})
    assert run(tree, "--record") == 1
    assert drift(capsys) == [f"drift: {C.APK}: refusing to record: is a zip but holds no AndroidManifest.xml"]


def test_record_refuses_a_dirty_app_source(tree, capsys):
    added = tree / C.APP_SOURCE / "app" / "New.kt"
    added.parent.mkdir(parents=True, exist_ok=True)
    added.write_text("// uncommitted\n")
    assert run(tree, "--record") == 2
    assert capsys.readouterr().err.startswith(
        f"setup: --record cannot pin {C.APK}: mobile/android has uncommitted changes")


# ---- the milestone report and the two markdown copies: one flipped byte each

def test_flipped_byte_in_the_staged_report_docx_is_caught(tree, capsys):
    """The middle of a docx is deflate data, which the entries digest alone never reads (its CRCs live in the central
    directory): the entry that no longer inflates to its CRC is what turns this into drift."""
    path = tree / C.STAGED / "milestone-report.docx"
    raw = path.read_bytes()
    path.write_bytes(flip(raw, len(raw) // 2))
    assert C.zip_entries_digest(path) == C.load_record(tree)["milestone-report.docx"]["digest"]
    assert run(tree) == 1
    lines = drift(capsys)
    assert len(lines) == 1, lines
    assert lines[0].startswith("drift: milestone-report.docx: the copy in cache/carriers/published/milestone-report.docx "
                               "is not the published artifact (sha256-zip-entries damaged:")


def test_flipped_byte_in_the_staged_deployment_plan_is_caught(tree, capsys):
    path = tree / C.STAGED / "celo-mainnet-deployment-plan.md"
    raw = path.read_bytes()
    path.write_bytes(flip(raw, len(raw) // 2))
    assert run(tree) == 1
    lines = drift(capsys)
    assert len(lines) == 1, lines
    assert lines[0].startswith("drift: celo-mainnet-deployment-plan.md: the copy in "
                               "cache/carriers/published/celo-mainnet-deployment-plan.md is not the published artifact "
                               "(sha256 ")


def test_flipped_byte_in_the_staged_findings_is_caught(tree, capsys):
    path = tree / C.STAGED / "findings.md"
    raw = path.read_bytes()
    path.write_bytes(flip(raw, len(raw) // 2))
    assert run(tree) == 1
    lines = drift(capsys)
    assert len(lines) == 1, lines
    assert lines[0].startswith("drift: findings.md: the copy in cache/carriers/published/findings.md is not the "
                               "published artifact (sha256 ")


def test_edited_report_markdown_is_caught_on_the_report_alone(tree, capsys):
    """Each renderer runs over its own carrier's markdown: the report's edit reaches the report and no proposal row."""
    with (tree / C.REPORT_MARKDOWN).open("a") as f:
        f.write("\nA sentence added after the report was published.\n")
    assert run(tree) == 1
    lines = drift(capsys)
    assert any(l.startswith("drift: milestone-report.docx: source docs/milestone-roadmap-report.md moved")
               for l in lines)
    assert any(l.startswith("drift: milestone-report.docx: a fresh render is sha256-zip-entries ") for l in lines)
    assert not any(l.startswith("drift: proposal.") for l in lines)
