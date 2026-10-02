"""Gate the four proposal carriers published into the workspace Files against the repo source they derive from.

    .venv/bin/python tools/check_carriers.py           # exit 1 if a source moved or a carrier would render differently
    .venv/bin/python tools/check_carriers.py --json    # the same checks as one JSON report on stdout
    .venv/bin/python tools/check_carriers.py --record  # rewrite docs/carriers.json from the staged published copies

Carriers (docs/carriers.json is the publish record: per carrier its size, digest and the sources it was made from):
  proposal.pdf      tools/render_proposal_pdf.py over docs/prezenti-proposal.md, tools/print/proposal.css and
                    assets/brand/biorig-lockup.png. Byte-deterministic: two renders of the same markdown are
                    identical, and the published copy equals a fresh render. Compared by sha256.
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

Checks, one line per carrier per check:
  sources   every source the record names still hashes to the recorded value (a moved source is a carrier
            that was not republished)
  derive    a fresh pdf/docx render into a temp dir, or the md/png file it is copied from, equals the record
  staged    each file in cache/carriers/published/ (the bytes downloaded from the workspace Files; git-ignored)
            equals the record: the copy in Files is the artefact the publish flow produced. Absent directory:
            a note, and the repo-side checks still decide the exit status.

The workspace Files are not reachable from the repo, so nothing here fetches them: an operator downloads the
published bytes into the staging directory. --record refuses (exit 1) unless all four staged copies agree with a
fresh render, so the record only ever describes a state in which Files matches the pipeline. The publish flow is
DEPLOY.md section 9. Offline: no network, no RPC.

Exit status: 0 clean, 1 drift (or --record refused), 2 setup failure (record missing or unreadable, a renderer
missing, a render failing, or --record without all four staged copies).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

RECORD = Path("docs") / "carriers.json"  # paths are relative to --root
STAGED = Path("cache") / "carriers" / "published"
MARKDOWN = Path("docs") / "prezenti-proposal.md"
PDF_RENDERER = Path("tools") / "render_proposal_pdf.py"
DOCX_RENDERER = Path("tools") / "render_proposal_docx.py"
STYLESHEET = Path("tools") / "print" / "proposal.css"
LOCKUP = Path("assets") / "brand" / "biorig-lockup.png"
DIAGRAM_SVG = Path("assets") / "BioRig_Architecture_v5.svg"
RASTER = Path("BioRig_Architecture_Pro.png")

LOCATION = "the published copy in the workspace Files"
REMEDY = "re-render, republish, stage the published bytes, then --record (DEPLOY.md section 9)"
SHA256 = "sha256"
ZIP_ENTRIES = "sha256-zip-entries"


@dataclass(frozen=True)
class Carrier:
    name: str
    algorithm: str
    sources: tuple[Path, ...]
    renderer: Path | None = None  # rendered from MARKDOWN by this script ...
    copy_of: Path | None = None   # ... or published as this file, byte for byte


CARRIERS: tuple[Carrier, ...] = (
    Carrier("proposal.pdf", SHA256, (MARKDOWN, PDF_RENDERER, STYLESHEET, LOCKUP), renderer=PDF_RENDERER),
    Carrier("proposal.docx", ZIP_ENTRIES, (MARKDOWN, DOCX_RENDERER, LOCKUP), renderer=DOCX_RENDERER),
    Carrier("proposal.md", SHA256, (MARKDOWN,), copy_of=MARKDOWN),
    Carrier("architecture.png", SHA256, (DIAGRAM_SVG, RASTER), copy_of=RASTER),
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


def check_derived(root: Path, carrier: Carrier, entry: dict, out_dir: Path) -> Line:
    have, _ = derived(root, carrier, out_dir)
    want = entry["digest"]
    what = "a fresh render" if carrier.renderer else f"the committed {carrier.copy_of.as_posix()}"
    if have == want:
        return Line(carrier.name, "derive", "ok", f"{what} matches the published {entry['algorithm']} {short(want)}")
    return Line(carrier.name, "derive", "drift",
                f"{what} is {entry['algorithm']} {have}, {LOCATION} is {want}; {REMEDY}")


def check_staged(staged: Path, record: dict[str, dict], root: Path) -> list[Line]:
    shown = staged.relative_to(root) if staged.is_relative_to(root) else staged
    if not staged.is_dir() or not any(staged.iterdir()):
        return [Line("", "staged", "note",
                     f"no staged copies in {shown}/; download the four carriers from the workspace Files into it "
                     f"to compare them (DEPLOY.md section 9)")]
    lines = []
    for carrier in CARRIERS:
        path, entry = staged / carrier.name, record[carrier.name]
        if not path.exists():
            lines.append(Line(carrier.name, "staged", "note", f"not staged in {shown}/"))
        elif (have := digest(path, entry["algorithm"])) == entry["digest"]:
            lines.append(Line(carrier.name, "staged", "ok", "staged copy matches the record"))
        else:
            lines.append(Line(carrier.name, "staged", "drift",
                              f"the copy in {shown / carrier.name} is not the published artifact "
                              f"({entry['algorithm']} {short(have)}, record {short(entry['digest'])})"))
    return lines


def check(root: Path, staged: Path) -> list[Line]:
    record = load_record(root)
    missing = [c.name for c in CARRIERS if c.name not in record]
    if missing:
        raise SetupError(f"{RECORD} has no entry for {', '.join(missing)}; run --record")
    lines: list[Line] = []
    with tempfile.TemporaryDirectory(prefix="carriers-") as tmp:
        for carrier in CARRIERS:
            lines += check_sources(root, carrier, record[carrier.name])
            lines.append(check_derived(root, carrier, record[carrier.name], Path(tmp)))
    return lines + check_staged(staged, record, root)


def record(root: Path, staged: Path) -> tuple[list[Line], bool]:
    """(lines, written). Writes the record only when every staged copy equals what the pipeline produces now."""
    absent = [c.name for c in CARRIERS if not (staged / c.name).exists()]
    if absent:
        raise SetupError(f"--record needs all four published copies staged in {staged}; missing {', '.join(absent)}")
    lines, entries = [], []
    with tempfile.TemporaryDirectory(prefix="carriers-") as tmp:
        for carrier in CARRIERS:
            want, _ = derived(root, carrier, Path(tmp))
            path = staged / carrier.name
            have = digest(path, carrier.algorithm)
            if have != want:
                lines.append(Line(carrier.name, "record", "drift",
                                  f"refusing to record: the copy in {path.name} is not the published artifact the "
                                  f"pipeline produces ({carrier.algorithm} {short(have)}, fresh {short(want)})"))
                continue
            entries.append({"name": carrier.name, "size": path.stat().st_size, "algorithm": carrier.algorithm,
                            "digest": want,
                            "sources": {rel.as_posix(): sha256_file(root / rel) for rel in carrier.sources}})
    if lines:
        return lines, False
    (root / RECORD).write_text(render_record(entries))
    return [Line(e["name"], "record", "ok", f"recorded {e['algorithm']} {short(e['digest'])}") for e in entries], True


# --------------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--record", action="store_true", help=f"rewrite {RECORD} from the staged published copies")
    ap.add_argument("--json", action="store_true", help="print a machine-readable report instead of lines")
    ap.add_argument("--root", type=Path, default=ROOT, help="checkout to operate on (default: this repo)")
    ap.add_argument("--staged", type=Path, help=f"staged published copies (default: <root>/{STAGED})")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    staged = (args.staged or root / STAGED).resolve()
    try:
        if args.record:
            lines, written = record(root, staged)
            code = 0 if written else 1
        else:
            lines = check(root, staged)
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
