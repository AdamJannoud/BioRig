"""Gate the committed Android screen renders against their manifest.

    .venv/bin/python tools/check_screenshots.py                     # mobile/android/screenshots, exit 1 on a finding
    .venv/bin/python tools/check_screenshots.py --dir DIR --json    # another render directory, findings as JSON

`./gradlew :app:renderScreens` (mobile/android) draws the six screens of ui/Screens.kt, light and dark, on the JVM
under Robolectric and writes <screen>-<mode>.png plus manifest.json beside them. The renders are byte-stable, so
the manifest's sha256 is a real claim about the committed bytes. Findings:
  missing    a screen/mode pair the app has (SCREENS x MODES) is not in the manifest, or is listed twice
  absent     the manifest lists a file that is not on disk
  digest     a PNG's sha256 disagrees with the manifest: re-rendered or edited without regenerating the manifest
  size       a PNG's IHDR width/height disagrees with the manifest or the recorded device spec
  stray      a PNG on disk that the manifest does not list
  manifest   the manifest is unreadable, or a path in it leaves the render directory or is not a .png

Nothing is rendered here: the check needs no JDK or Android SDK. Regenerate with `:app:renderScreens` and commit the
PNGs and manifest.json together.

Exit status: 0 clean, 1 findings, 2 setup failure (no render directory or no manifest.json).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = ROOT / "mobile" / "android" / "screenshots"
SCREENS = ("setup", "fix", "photos", "submit", "queue", "tree")  # ui/Screens.kt, in flow order
MODES = ("light", "dark")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_size(path: Path) -> tuple[int, int] | None:
    """(width, height) from the IHDR chunk, or None when the file is not a PNG."""
    head = path.read_bytes()[:24]
    if len(head) < 24 or head[:8] != PNG_SIGNATURE or head[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", head[16:24])


def check(render_dir: Path) -> list[dict]:
    """Findings for one render directory, each {"kind", "path", "detail"}. Raises FileNotFoundError on setup gaps."""
    manifest_path = render_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"no manifest.json in {render_dir}")
    findings: list[dict] = []

    def find(kind: str, path: str, detail: str) -> None:
        findings.append({"kind": kind, "path": path, "detail": detail})

    try:
        manifest = json.loads(manifest_path.read_text())
        renders = manifest["renders"]
        device = manifest.get("device", {})
        if not isinstance(renders, list):
            raise TypeError("renders is not a list")
    except (ValueError, KeyError, TypeError) as exc:
        find("manifest", "manifest.json", f"not a render manifest ({exc!r})")
        return findings

    want_size = (device.get("width_px"), device.get("height_px"))
    seen: dict[tuple[str, str], int] = {}
    listed: set[str] = set()
    for i, row in enumerate(renders):
        try:
            screen, mode, rel = str(row["screen"]), str(row["mode"]), str(row["path"])
            sha, width, height = str(row["sha256"]), int(row["width"]), int(row["height"])
        except (KeyError, TypeError, ValueError) as exc:
            find("manifest", f"renders[{i}]", f"incomplete entry ({exc!r})")
            continue
        seen[(screen, mode)] = seen.get((screen, mode), 0) + 1
        pure = PurePosixPath(rel)
        if pure.is_absolute() or ".." in pure.parts or len(pure.parts) != 1 or pure.suffix != ".png":
            find("manifest", rel, "a render path must be a .png file name inside the render directory")
            continue
        listed.add(rel)
        png = render_dir / rel
        if not png.is_file():
            find("absent", rel, f"listed for {screen}/{mode} but not on disk")
            continue
        have = hashlib.sha256(png.read_bytes()).hexdigest()
        if have != sha:
            find("digest", rel, f"sha256 {have[:12]}… on disk, {sha[:12]}… in the manifest")
        size = png_size(png)
        if size is None:
            find("size", rel, "not a PNG")
        elif size != (width, height):
            find("size", rel, f"{size[0]}x{size[1]} on disk, {width}x{height} in the manifest")
        elif None not in want_size and size != want_size:
            find("size", rel, f"{size[0]}x{size[1]}, not the device spec's {want_size[0]}x{want_size[1]}")

    for screen in SCREENS:
        for mode in MODES:
            n = seen.get((screen, mode), 0)
            if n != 1:
                find("missing", f"{screen}-{mode}",
                     "no render in the manifest" if n == 0 else f"listed {n} times in the manifest")
    for png in sorted(render_dir.glob("*.png")):
        if png.name not in listed:
            find("stray", png.name, "on disk but not in the manifest")
    return findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="render directory holding manifest.json")
    ap.add_argument("--json", action="store_true", help="print the findings as JSON")
    args = ap.parse_args(argv)
    try:
        findings = check(args.dir)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 2
    if args.json:
        print(json.dumps({"dir": str(args.dir), "findings": findings}, indent=1))
    else:
        for f in findings:
            print(f"FAIL {f['kind']:<8} {f['path']}: {f['detail']}")
        if not findings:
            print(f"{len(SCREENS) * len(MODES)} renders ({len(SCREENS)} screens x {'/'.join(MODES)}) match manifest.json")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
