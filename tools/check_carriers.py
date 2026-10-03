"""Gate the carriers published into the workspace Files against the repo source they derive from.

    .venv/bin/python tools/check_carriers.py           # exit 1 if a source moved or a carrier would render differently
    .venv/bin/python tools/check_carriers.py --json    # the same checks as one JSON report on stdout
    .venv/bin/python tools/check_carriers.py --record  # rewrite docs/carriers.json from the staged published copies
    .venv/bin/python tools/check_carriers.py --require-staged  # publish-flow gate: the staging notes below fail (see under 'Checks')

Carriers (docs/carriers.json is the publish record: per carrier its size, digest and the sources it was made from):
  proposal.pdf      tools/render_proposal_pdf.py over docs/prezenti-proposal.md, tools/print/proposal.css and
                    assets/brand/biorig-lockup.png. Byte-deterministic on one machine: two renders of the same
                    markdown are identical, and in the publishing environment the published copy equals a fresh
                    render. Compared by sha256. Those bytes come from Chromium print-to-PDF, so they depend on the
                    browser build and on the brand fonts (Caladea, Lato) being installed: a fresh clone in CI without
                    them renders different bytes from an unchanged source (see `derive` below).
  proposal.docx     tools/render_proposal_docx.py over the same markdown and lockup. Its content is deterministic
                    but its bytes are not: python-docx stamps the wall-clock time into every zip entry (DOS time and
                    date, once in the local header and once in the central directory). Two renders seconds apart
                    differed by 88 bytes, 4 bytes x 22 entries, while all 22 entries had identical CRC32 and size and
                    the extracted XML parts were byte-identical; the published copy measured the same against a
                    fresh render. So it is compared by a normalized digest, sha256 over the entries sorted by name of
                    `name \\0 crc32 (8 hex digits) \\0 uncompressed size \\n`. Do not turn this into a byte
                    comparison, and do not pin the stamp in the renderer: the first would fail on every render, the
                    second would change the published artefact to suit its gate.
  proposal.md       a plain copy of docs/prezenti-proposal.md. sha256.
  architecture.png  a plain copy of the committed BioRig_Architecture_Pro.png, itself rendered from
                    assets/BioRig_Architecture_v5.svg. sha256.
  architecture.svg  a plain copy of assets/BioRig_Architecture_v5.svg, published so the diagram is downloadable as
                    a vector. sha256.
  architecture-slide.png  the same diagram published as a raster at the size its vector source declares (2400 x 2124,
                    the 2x slide-size export), rendered by tools/generate_architecture.py --png-out --png-scale 2.
                    There is no committed counterpart to copy, and it is deliberately not byte-compared: the same
                    scene painted by a rebuilt Pillow/FreeType moves a thousand-odd pixels on glyph edges from
                    unchanged source (measured in that tool's --check, which is why it uses provenance for the
                    raster too). It is pinned to its source the same way: the published raster must decode at the
                    size the committed SVG declares and carry the generator's tEXt chunks naming a sha256 of those
                    exact SVG bytes. Read from the staged copy, so no renderer runs here; a raster rendered from any
                    other SVG bytes - an earlier revision of the diagram - is caught by the chunk it carries.
  android-debug.apk  the debug APK published to reviewers, built from mobile/android at the commit the record names.
                    A rebuild is neither quick (the Android SDK, about a minute) nor reproducible across machines,
                    and CI has no SDK, so the published bytes are not re-derived here. The record pins instead the git
                    tree of mobile/android the APK was built from, and the check fails the moment this checkout's app
                    source stops matching it: any change to any file the app is built from means the published APK
                    predates it. The published bytes themselves are still compared with the record.

Checks, one line per carrier per check:
  sources   every source the record names still hashes to the recorded value (a moved source is a carrier
            that was not republished)
  derive    a fresh pdf/docx render into a temp dir, or the md/png/svg file it is copied from, equals the record; for
            architecture-slide.png the staged raster's own provenance must match the committed SVG, and for
            android-debug.apk the derivation is the app-source tree instead (see `tree`). Byte-equality of a raw
            render (proposal.pdf) is attested only in the publishing environment, where the published copy is staged
            (pinned browser build and brand fonts); without a staged copy the line is a note on stdout saying the
            render's bytes are not attested here, and the recorded source digests, the docx/md/png/svg comparisons and
            any staged copies present still decide the exit status.
  tree      android-debug.apk only: the recorded git tree of the app source still matches this checkout, so the
            published APK was built from the app source as it stands. A file added under mobile/android and never
            committed counts too, since gradle compiles untracked files: the tree hash alone would miss it. Needs a
            git checkout; elsewhere it is a note.
  staged    each file in cache/carriers/published/ (the bytes downloaded from the workspace Files; git-ignored)
            equals the record: the copy in Files is the artefact the publish flow produced. Absent directory:
            a note, and the repo-side checks still decide the exit status.

--require-staged (the closing gate of a publish run, DEPLOY.md section 9) removes that leniency: an absent or partial
staging directory, and a pdf render or a slide raster whose bytes cannot be attested without a staged copy, become
drift and the run exits 1, so a publish that never staged the bytes it uploaded cannot read green. Mutually exclusive
with --record.

The workspace Files are not reachable from the repo, so nothing here fetches them: an operator downloads the
published bytes into the staging directory. --record refuses (exit 1) unless every staged copy agrees with what its
source produces - a fresh render, the file it is copied from, the SVG its provenance names, or, for the APK, an
Android package plus a clean app-source tree - so the record only ever describes a state in which Files matches the
pipeline. The publish flow is DEPLOY.md section 9. Offline: no network, no RPC.

Exit status: 0 clean, 1 drift (or --record refused), 2 setup failure (record missing or unreadable, a renderer
missing, a render failing, or --record with a published copy unstaged).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DIAGRAM_IMPORT_ERROR = ""
try:  # the diagram generator owns the tEXt key names; importing it needs Pillow, which the gate otherwise does not
    sys.path.insert(0, str(ROOT))
    from tools import generate_architecture as diagram  # noqa: E402
except ImportError as exc:  # pragma: no cover - the provenance check reports this instead of failing the whole gate
    diagram = None  # type: ignore[assignment]
    DIAGRAM_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

RECORD = Path("docs") / "carriers.json"  # paths are relative to --root
STAGED = Path("cache") / "carriers" / "published"
MARKDOWN = Path("docs") / "prezenti-proposal.md"
PDF_RENDERER = Path("tools") / "render_proposal_pdf.py"
DOCX_RENDERER = Path("tools") / "render_proposal_docx.py"
STYLESHEET = Path("tools") / "print" / "proposal.css"
LOCKUP = Path("assets") / "brand" / "biorig-lockup.png"
DIAGRAM_SVG = Path("assets") / "BioRig_Architecture_v5.svg"
RASTER = Path("BioRig_Architecture_Pro.png")
ARCH_GENERATOR = Path("tools") / "generate_architecture.py"
SLIDE_PNG = "architecture-slide.png"
APK = "android-debug.apk"
APP_SOURCE = Path("mobile") / "android"

LOCATION = "the published copy in the workspace Files"
REMEDY = "re-render, republish, stage the published bytes, then --record (DEPLOY.md section 9)"
SHA256 = "sha256"
ZIP_ENTRIES = "sha256-zip-entries"


@dataclass(frozen=True)
class Carrier:
    name: str
    algorithm: str
    sources: tuple[Path, ...]
    renderer: Path | None = None       # rendered from MARKDOWN by this script ...
    copy_of: Path | None = None        # ... or published as this file, byte for byte ...
    provenance_of: Path | None = None  # ... or a raster pinned to this SVG by the tEXt chunks it carries ...
    build_source: Path | None = None   # ... or a binary pinned to this committed git tree
    environment_bound: bool = False    # its raw bytes are reproducible only where the render environment is pinned


CARRIERS: tuple[Carrier, ...] = (
    Carrier("proposal.pdf", SHA256, (MARKDOWN, PDF_RENDERER, STYLESHEET, LOCKUP), renderer=PDF_RENDERER,
            environment_bound=True),
    Carrier("proposal.docx", ZIP_ENTRIES, (MARKDOWN, DOCX_RENDERER, LOCKUP), renderer=DOCX_RENDERER),
    Carrier("proposal.md", SHA256, (MARKDOWN,), copy_of=MARKDOWN),
    Carrier("architecture.png", SHA256, (DIAGRAM_SVG, RASTER), copy_of=RASTER),
    Carrier("architecture.svg", SHA256, (DIAGRAM_SVG,), copy_of=DIAGRAM_SVG),
    Carrier(SLIDE_PNG, SHA256, (DIAGRAM_SVG, ARCH_GENERATOR), provenance_of=DIAGRAM_SVG),
    Carrier(APK, SHA256, (), build_source=APP_SOURCE),
)


class SetupError(RuntimeError):
    """The gate cannot run at all: no record, a renderer missing or failing, or nothing staged to record from."""


@dataclass(frozen=True)
class Line:
    carrier: str
    check: str
    status: str  # ok | drift | note
    detail: str

    def __str__(self) -> str:
        return f"{self.status}: {self.carrier}: {self.detail}" if self.carrier else f"{self.status}: {self.detail}"


# --------------------------------------------------------------------------- digests

def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def zip_entries_digest(path: Path) -> str:
    """sha256 over the zip's entries sorted by name, each `name \\0 crc32 \\0 size \\n`: blind to the per-entry
    timestamps python-docx writes, sensitive to any change in an entry's content, name or presence."""
    h = hashlib.sha256()
    with zipfile.ZipFile(path) as z:
        for info in sorted(z.infolist(), key=lambda i: i.filename):
            h.update(f"{info.filename}\0{info.CRC:08x}\0{info.file_size}\n".encode())
    return h.hexdigest()


def digest(path: Path, algorithm: str) -> str:
    if algorithm == ZIP_ENTRIES:
        try:
            return zip_entries_digest(path)
        except zipfile.BadZipFile:
            return "not-a-zip:" + sha256_file(path)
    return sha256_file(path)


def short(value: str) -> str:
    return value[:12]


# --------------------------------------------------------------------------- record

def load_record(root: Path) -> dict[str, dict]:
    path = root / RECORD
    if not path.exists():
        raise SetupError(f"{RECORD} missing; stage the published copies and run --record (DEPLOY.md section 9)")
    try:
        carriers = json.loads(path.read_text())["carriers"]
        return {c["name"]: c for c in carriers}
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise SetupError(f"{RECORD} is not a carriers record ({exc!r})") from exc


def render_record(entries: list[dict]) -> str:
    record = {"location": LOCATION, "carriers": entries,
              "about": "Written by tools/check_carriers.py --record; checked by tools/check_carriers.py."}
    return json.dumps(record, indent=2, sort_keys=True) + "\n"


# --------------------------------------------------------------------------- render

def render(root: Path, carrier: Carrier, out_dir: Path) -> Path:
    """Run the carrier's renderer over the markdown in a subprocess (each renderer resolves its stylesheet and
    lockup against its own checkout) and return the output path."""
    script = root / carrier.renderer
    if not script.exists():
        raise SetupError(f"renderer {carrier.renderer} missing")
    out = out_dir / carrier.name
    run = subprocess.run([sys.executable, str(script), "--src", str(root / MARKDOWN), "--out", str(out)],
                         cwd=root, capture_output=True, text=True, timeout=300)
    if run.returncode != 0 or not out.exists():
        tail = "\n".join((run.stdout + run.stderr).strip().splitlines()[-15:])
        raise SetupError(f"{carrier.renderer} failed (exit {run.returncode}):\n{tail}")
    return out


def derived(root: Path, carrier: Carrier, out_dir: Path) -> tuple[str, Path]:
    """(digest of what the pipeline produces for this carrier now, the file it was taken from)."""
    path = render(root, carrier, out_dir) if carrier.renderer else root / carrier.copy_of
    if not path.exists():
        raise SetupError(f"{carrier.copy_of} missing")
    return digest(path, carrier.algorithm), path


# --------------------------------------------------------------------------- checks

def check_sources(root: Path, carrier: Carrier, entry: dict) -> list[Line]:
    recorded: dict[str, str] = entry.get("sources", {})
    lines = []
    for rel in carrier.sources:
        if rel.as_posix() not in recorded:
            lines.append(Line(carrier.name, "sources", "drift",
                              f"source {rel.as_posix()} is not in the record; {REMEDY}"))
    for rel, want in sorted(recorded.items()):
        path = root / rel
        if not path.exists():
            lines.append(Line(carrier.name, "sources", "drift", f"source {rel} missing; {REMEDY}"))
        elif (have := sha256_file(path)) != want:
            lines.append(Line(carrier.name, "sources", "drift",
                              f"source {rel} moved (recorded {short(want)}, tree {short(have)}); {REMEDY}"))
    n = len(recorded)
    return lines or [Line(carrier.name, "sources", "ok", f"{n}/{n} sources match the record")]


# --------------------------------------------------------------------------- app source

def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(("git", "-C", str(root), *args), capture_output=True, text=True, timeout=60)


def app_source_dirty(root: Path, path: Path) -> list[str] | None:
    """The files under `path` that are not what HEAD holds: modified (staged or not), plus untracked ones that are not
    ignored, since gradle compiles those too and the committed tree hash cannot see them. None where git cannot say."""
    rel = path.as_posix()
    modified = git(root, "diff", "--name-only", "HEAD", "--", rel)
    untracked = git(root, "ls-files", "--others", "--exclude-standard", "--", rel)
    if modified.returncode != 0 or untracked.returncode != 0:
        return None
    lines = modified.stdout.splitlines() + untracked.stdout.splitlines()
    return list(dict.fromkeys(line for line in lines if line.strip()))


def app_source_moved(root: Path, tree: str, path: Path) -> list[str] | None:
    """The files under `path` that differ from `tree`: what has been committed since HEAD's copy of `path` moved off
    it, plus any uncommitted edit. [] when the app source is still exactly that tree, None where git cannot answer
    (not a checkout, or this checkout does not hold that tree object).

    Both sides of the committed comparison are the same subtree on purpose: a bare tree object is rooted at itself, so
    comparing it against a checkout by pathspec filters its own entries away and reports every file as new.
    """
    rel = path.as_posix()
    committed = git(root, "diff", "--name-only", tree, f"HEAD:{rel}")
    dirty = app_source_dirty(root, path)
    if committed.returncode != 0 or dirty is None:
        return None
    moved = [f"{rel}/{line}" for line in committed.stdout.splitlines() if line.strip()] + dirty
    return list(dict.fromkeys(moved))


def app_source_tree(root: Path, path: Path) -> str | None:
    """The git tree hash of `path` at HEAD, or None where this is not a git checkout."""
    run = git(root, "rev-parse", f"HEAD:{path.as_posix()}")
    return run.stdout.strip() if run.returncode == 0 else None


def android_package_problem(path: Path) -> str | None:
    """Why `path` is not an Android package, or None: it must be a zip holding a manifest and a dex."""
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
    except (zipfile.BadZipFile, OSError) as exc:
        return f"is not a zip ({exc})"
    if "AndroidManifest.xml" not in names:
        return "is a zip but holds no AndroidManifest.xml"
    if not any(name.endswith(".dex") for name in names):
        return "is a zip but holds no classes.dex"
    return None


def check_build_source(root: Path, carrier: Carrier, entry: dict) -> Line:
    rel = carrier.build_source.as_posix()
    recorded = entry.get("build_source") or {}
    want = recorded.get("tree")
    if recorded.get("path") != rel or not want:
        return Line(carrier.name, "tree", "drift",
                    f"the record does not pin {rel} as the app source this carrier was built from; {REMEDY}")
    moved = app_source_moved(root, want, carrier.build_source)
    if moved is None:
        return Line(carrier.name, "tree", "note",
                    f"the app source the published apk was built from is not checked here: this is not a git checkout, "
                    f"or it does not hold the recorded tree {short(want)} of {rel}")
    if not moved:
        return Line(carrier.name, "tree", "ok",
                    f"the app source {rel} is the tree {short(want)} the published apk was built from")
    shown = ", ".join(moved[:4]) + (f" and {len(moved) - 4} more" if len(moved) > 4 else "")
    return Line(carrier.name, "tree", "drift",
                f"the app source {rel} has moved past the tree {short(want)} the published apk was built from "
                f"({shown}): rebuild the apk from this tree, republish it, then --record (DEPLOY.md section 9)")


# --------------------------------------------------------------------------- slide raster

SVG_OPEN_SIZE = re.compile(r"<svg\b[^>]*?\bwidth=\"([0-9.]+)\"[^>]*?\bheight=\"([0-9.]+)\"")


def svg_declared_size(svg: str) -> tuple[int, int] | None:
    """The pixel size a generated SVG declares for itself, which is the size a 1:1 raster of it must have."""
    match = SVG_OPEN_SIZE.search(svg)
    return (round(float(match.group(1))), round(float(match.group(2)))) if match else None


def provenance_problem(png: Path, svg: Path) -> str | None:
    """Why `png` is not a raster of `svg`'s bytes, or None when its size and its embedded provenance say it is.

    The generator stamps bio-rig-source-svg-sha256 and bio-rig-generator into every raster it paints, so a raster
    repainted, resized or re-saved by anything else stops naming these bytes. That is the check the generator applies
    to the committed raster, and unlike a pixel comparison it holds across environments.
    """
    if diagram is None:
        return f"the diagram generator's provenance keys cannot be imported here ({DIAGRAM_IMPORT_ERROR})"
    try:
        from PIL import Image
    except ImportError:
        return "Pillow is not installed here, so its embedded provenance cannot be read"
    if not png.is_file():
        return "missing"
    try:
        with Image.open(png) as im:
            im.load()
            size, text = im.size, getattr(im, "text", {}) or {}
    except Exception as exc:  # noqa: BLE001 - any decode failure means this is not a usable raster
        return f"does not decode ({exc})"
    want = svg_declared_size(svg.read_text())
    if want is None:
        return f"the vector source {svg.name} declares no pixel size"
    if size != want:
        return f"is {size[0]}x{size[1]} px, the vector source declares {want[0]}x{want[1]}"
    named = text.get(diagram.PNG_SVG_SHA_KEY)
    if named != sha256_file(svg):
        return (f"was rendered from other svg bytes: its {diagram.PNG_SVG_SHA_KEY} chunk is {named or 'absent'}, "
                f"the committed {svg.name} is {sha256_file(svg)}")
    if text.get(diagram.PNG_GENERATOR_KEY) != diagram.GENERATOR:
        return (f"does not name {diagram.GENERATOR} as the generator that wrote it "
                f"({diagram.PNG_GENERATOR_KEY} is {text.get(diagram.PNG_GENERATOR_KEY) or 'absent'})")
    return None


def check_provenance(root: Path, carrier: Carrier, staged: Path, require_staged: bool) -> Line:
    svg = root / carrier.provenance_of
    if not svg.exists():
        return Line(carrier.name, "derive", "drift", f"source {carrier.provenance_of.as_posix()} missing; {REMEDY}")
    path = staged / carrier.name
    if not path.is_file():
        detail = (f"the published raster's provenance is not checked here: no published copy is staged in {path}, and "
                  f"only the published bytes carry the tEXt chunks that name the svg they were rendered from")
        return Line(carrier.name, "derive", "drift" if require_staged else "note",
                    f"{detail}; {REMEDY}" if require_staged else detail)
    problem = provenance_problem(path, svg)
    if problem is None:
        size = svg_declared_size(svg.read_text()) or (0, 0)
        return Line(carrier.name, "derive", "ok",
                    f"the staged raster is the {size[0]}x{size[1]} raster of {carrier.provenance_of.as_posix()} "
                    f"(sha256 {short(sha256_file(svg))}), the bytes its provenance names")
    return Line(carrier.name, "derive", "drift", f"the staged {carrier.name} {problem}; {REMEDY}")


def check_derived(root: Path, carrier: Carrier, entry: dict, out_dir: Path, staged: Path,
                  require_staged: bool = False) -> Line:
    have, _ = derived(root, carrier, out_dir)
    want = entry["digest"]
    what = "a fresh render" if carrier.renderer else f"the committed {carrier.copy_of.as_posix()}"
    if carrier.environment_bound and not (staged / carrier.name).is_file():
        verdict = "matches" if have == want else f"is {short(have)}, not"
        if require_staged:
            return Line(carrier.name, "derive", "drift",
                        f"{what} {verdict} the published {entry['algorithm']} {short(want)}, but its bytes are not "
                        f"attested: --require-staged needs the published copy staged in {staged / carrier.name}, where "
                        f"the browser build and brand fonts are pinned; {REMEDY}")
        return Line(carrier.name, "derive", "note",
                    f"{what} {verdict} the published {entry['algorithm']} {short(want)}, but its bytes are not "
                    f"attested in this environment: no published copy is staged, and Chromium print-to-PDF bytes "
                    f"depend on the browser build and the brand fonts, so byte-equality is checked only where the "
                    f"published copies are staged (DEPLOY.md section 9); the recorded source digests are enforced")
    if have == want:
        return Line(carrier.name, "derive", "ok", f"{what} matches the published {entry['algorithm']} {short(want)}")
    return Line(carrier.name, "derive", "drift",
                f"{what} is {entry['algorithm']} {have}, {LOCATION} is {want}; {REMEDY}")


def check_derivation(root: Path, carrier: Carrier, entry: dict, out_dir: Path, staged: Path,
                     require_staged: bool = False) -> Line:
    """The one line that says how this carrier is tied to its source: a build tree, embedded provenance, or bytes."""
    if carrier.build_source is not None:
        return check_build_source(root, carrier, entry)
    if carrier.provenance_of is not None:
        return check_provenance(root, carrier, staged, require_staged)
    return check_derived(root, carrier, entry, out_dir, staged, require_staged)


def check_staged(staged: Path, record: dict[str, dict], root: Path,
                 require_staged: bool = False) -> list[Line]:
    shown = staged.relative_to(root) if staged.is_relative_to(root) else staged
    if not staged.is_dir() or not any(staged.iterdir()):
        if require_staged:
            return [Line("", "staged", "drift",
                         f"no staged copies in {shown}/, but --require-staged needs every published carrier "
                         f"staged to attest it (DEPLOY.md section 9)")]
        return [Line("", "staged", "note",
                     f"no staged copies in {shown}/; download the published carriers from the workspace Files into it "
                     f"to compare them (DEPLOY.md section 9)")]
    lines = []
    for carrier in CARRIERS:
        path, entry = staged / carrier.name, record[carrier.name]
        if not path.exists():
            status = "drift" if require_staged else "note"
            detail = f"not staged in {shown}/"
            if require_staged:
                detail += " (--require-staged needs it to attest the published bytes)"
            lines.append(Line(carrier.name, "staged", status, detail))
        elif (have := digest(path, entry["algorithm"])) == entry["digest"]:
            lines.append(Line(carrier.name, "staged", "ok", "staged copy matches the record"))
        else:
            lines.append(Line(carrier.name, "staged", "drift",
                              f"the copy in {shown / carrier.name} is not the published artifact "
                              f"({entry['algorithm']} {short(have)}, record {short(entry['digest'])})"))
    return lines


def check(root: Path, staged: Path, require_staged: bool = False) -> list[Line]:
    record = load_record(root)
    missing = [c.name for c in CARRIERS if c.name not in record]
    if missing:
        raise SetupError(f"{RECORD} has no entry for {', '.join(missing)}; run --record")
    lines: list[Line] = []
    with tempfile.TemporaryDirectory(prefix="carriers-") as tmp:
        for carrier in CARRIERS:
            if carrier.sources:
                lines += check_sources(root, carrier, record[carrier.name])
            lines.append(check_derivation(root, carrier, record[carrier.name], Path(tmp), staged, require_staged))
    return lines + check_staged(staged, record, root, require_staged)


def staged_problem(root: Path, carrier: Carrier, path: Path, out_dir: Path) -> str | None:
    """Why the staged copy is not what this carrier's source produces now, or None when it is."""
    if carrier.build_source is not None:
        return android_package_problem(path)
    if carrier.provenance_of is not None:
        return provenance_problem(path, root / carrier.provenance_of)
    want, _ = derived(root, carrier, out_dir)
    have = digest(path, carrier.algorithm)
    if have == want:
        return None
    return (f"the copy in {path.name} is not the published artifact the pipeline produces "
            f"({carrier.algorithm} {short(have)}, fresh {short(want)})")


def build_source_entry(root: Path, carrier: Carrier) -> dict:
    """The app source this carrier was built from, pinned by the git tree at HEAD. Refuses a dirty app tree: the
    record must name the committed source the published bytes came from."""
    tree = app_source_tree(root, carrier.build_source)
    if tree is None:
        raise SetupError(f"--record cannot pin {carrier.name}: {root} is not a git checkout, so the tree of "
                         f"{carrier.build_source} cannot be read")
    dirty = app_source_dirty(root, carrier.build_source)
    if dirty is None:
        raise SetupError(f"--record cannot pin {carrier.name}: {root} is not a git checkout, so uncommitted changes "
                         f"to {carrier.build_source} cannot be read")
    if dirty:
        raise SetupError(f"--record cannot pin {carrier.name}: {carrier.build_source} has uncommitted changes "
                         f"({', '.join(dirty[:4])}); commit the app source the apk was built from first")
    return {"path": carrier.build_source.as_posix(), "tree": tree}


def record(root: Path, staged: Path) -> tuple[list[Line], bool]:
    """(lines, written). Writes the record only when every staged copy is what its source produces now."""
    absent = [c.name for c in CARRIERS if not (staged / c.name).exists()]
    if absent:
        raise SetupError(f"--record needs every published copy staged in {staged}; missing {', '.join(absent)}")
    lines, entries = [], []
    with tempfile.TemporaryDirectory(prefix="carriers-") as tmp:
        for carrier in CARRIERS:
            path = staged / carrier.name
            if problem := staged_problem(root, carrier, path, Path(tmp)):
                lines.append(Line(carrier.name, "record", "drift", f"refusing to record: {problem}"))
                continue
            entry = {"name": carrier.name, "size": path.stat().st_size, "algorithm": carrier.algorithm,
                     "digest": digest(path, carrier.algorithm),
                     "sources": {rel.as_posix(): sha256_file(root / rel) for rel in carrier.sources}}
            if carrier.build_source is not None:
                entry["build_source"] = build_source_entry(root, carrier)
            entries.append(entry)
    if lines:
        return lines, False
    (root / RECORD).write_text(render_record(entries))
    return [Line(e["name"], "record", "ok", f"recorded {e['algorithm']} {short(e['digest'])}") for e in entries], True


# --------------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="print a machine-readable report instead of lines")
    ap.add_argument("--root", type=Path, default=ROOT, help="checkout to operate on (default: this repo)")
    ap.add_argument("--staged", type=Path, help=f"staged published copies (default: <root>/{STAGED})")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--record", action="store_true",
                      help=f"rewrite {RECORD} from the staged published copies")
    mode.add_argument("--require-staged", action="store_true",
                      help="publish-flow gate: the absent/partial-staging and unattested-pdf notes fail this run "
                           "(exit 1) instead of passing as notes (DEPLOY.md section 9)")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    staged = (args.staged or root / STAGED).resolve()
    try:
        if args.record:
            lines, written = record(root, staged)
            code = 0 if written else 1
        else:
            lines = check(root, staged, require_staged=args.require_staged)
            code = 1 if any(line.status == "drift" for line in lines) else 0
    except SetupError as exc:
        if args.json:
            print(json.dumps({"status": "setup", "exit": 2, "error": str(exc)}, indent=2))
        else:
            print(f"setup: {exc}", file=sys.stderr)
        return 2
    if args.json:
        report = {"status": "drift" if code else "clean", "exit": code, "record": RECORD.as_posix(),
                  "staged": staged.is_dir() and any(staged.iterdir()),
                  "checks": [vars(line) for line in lines]}
        print(json.dumps(report, indent=2))
    else:
        for line in lines:
            print(line, file=sys.stderr if line.status == "drift" else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
