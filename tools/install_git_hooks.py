"""Install the source-controlled git hooks into this checkout, or check that the installed copies match.

    python3 tools/install_git_hooks.py           # copy scripts/git-hooks/* into the checkout's hooks directory
    python3 tools/install_git_hooks.py --check   # exit 1 unless every installed hook is byte-identical and executable

The hooks live in scripts/git-hooks/ so they are reviewed and versioned like any other code; git never runs a file
from the working tree on its own, so each checkout installs them once (and again after a hook changes, which
--check reports). The hooks directory is wherever git says (`git rev-parse --git-path hooks`, which honours
core.hooksPath). A different hook already installed under the same name is left alone unless --force is given.

Exit status: 0 installed / all match, 1 a hook is missing, differs or is not executable (--check), or an install was
refused, 2 not a git checkout.
"""
from __future__ import annotations

import argparse
import filecmp
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "scripts" / "git-hooks"


def hooks_dir(repo: Path) -> Path:
    out = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-path", "hooks"], cwd=repo, text=True,
                         capture_output=True)
    if out.returncode != 0:
        sys.exit(f"install_git_hooks: not a git checkout: {repo}")
    return Path(out.stdout.strip())


def state(src: Path, dst: Path) -> str:
    if not dst.exists():
        return "missing"
    if not filecmp.cmp(src, dst, shallow=False):
        return "differs"
    if not os.access(dst, os.X_OK):
        return "not executable"
    return "ok"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="report only; exit 1 unless every hook matches")
    ap.add_argument("--force", action="store_true", help="overwrite a different hook of the same name")
    ap.add_argument("--repo-root", default=str(REPO_ROOT))
    args = ap.parse_args(argv)
    repo = Path(args.repo_root)
    source_dir = repo / "scripts" / "git-hooks"
    target = hooks_dir(repo)
    hooks = sorted(p for p in source_dir.iterdir() if p.is_file())
    bad = 0
    for src in hooks:
        dst = target / src.name
        now = state(src, dst)
        if args.check:
            print(f"{src.name}: {now} ({dst})")
            bad += now != "ok"
            continue
        if now == "ok":
            print(f"{src.name}: already installed ({dst})")
            continue
        if now == "differs" and not args.force:
            print(f"{src.name}: a different hook is installed at {dst}; refusing to overwrite it (use --force)")
            bad += 1
            continue
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        dst.chmod(0o755)
        print(f"{src.name}: installed {dst}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
