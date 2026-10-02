"""Sweep the gating documents for paths, links, commands, ports and env vars that the repository does not back.

    .venv/bin/python tools/check_docs_paths.py                       # the seven gating documents, exit 1 on a finding
    .venv/bin/python tools/check_docs_paths.py --docs FINDINGS.md    # report on other documents instead
    .venv/bin/python tools/check_docs_paths.py --json                # the same checks as one JSON report on stdout
    .venv/bin/python tools/check_docs_paths.py --repo-root DIR --allow docs/doc-path-allow.json

A document that names a file the checkout does not carry sends a reviewer to a dead end, and the usual cause is a
rename or a deletion that never reached the prose. Checks, per document:
  path       repo-relative paths in code spans, fences and prose resolve to a tracked file or directory (from the
             repo root or the document's directory; a bare basename may match any tracked file), or to a path git
             ignores (a generated or local artefact such as `.env` or the rendered mp4)
  link       relative markdown links and <img src> point at tracked files; #anchors match a heading's GitHub slug
  command    every script or module a bash/sh/shell/console fence runs is tracked; ignored files do not pass here,
             since a command that runs a local artefact fails on a clean clone
  port       documented ports agree with the defaults the code sets (Streamlit's config or its built-in 8501, the
             DEMO_PORT default in scripts/verify-demo.sh, RELAY_PORT in relay/config.py, the fork scripts' ports);
             the defaults are read from the code on every run, never written down here
  env        every environment variable the docs name is read by tracked code (a quoted literal, or $NAME in shell)
  submodule  with a .gitmodules present, README.md's Quick start fence initialises the submodules

Files are enumerated with `git ls-files`, never by walking the tree: the checkout holds a .venv/ and other local
state that must neither count as existing nor be scanned. "Tracked" includes a directory with a tracked file under
it and a submodule gitlink (lib/forge-std), which also covers any path beneath it.

The allowlist (docs/doc-path-allow.json) suppresses genuine false positives and user-supplied variables; each entry
needs a non-empty reason. On the default document set an entry that matched nothing is itself a finding, so the
list cannot outlive what it excuses.

Exit status: 0 clean, 1 findings, 2 setup failure (not a git checkout, allowlist missing or malformed).
"""
from __future__ import annotations

import argparse
import json
import posixpath
import re
import shlex
import subprocess
import sys
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_DOCS = ("README.md", "DEPLOY.md", "DEMO.md", "DEPLOY_DASHBOARD.md", "dashboard/README.md",
                "relay/README.md", "docs/relay-api.md")
DEFAULT_ALLOW = "docs/doc-path-allow.json"
KINDS = ("path", "link", "command", "port", "env", "submodule", "doc", "allowlist")

EXTENSIONS = {"py", "sh", "sol", "md", "json", "toml", "txt", "png", "svg", "yml", "yaml", "mp4", "wav", "css",
              "pdf", "docx", "diff", "lock", "example", "log", "sql", "html", "ico", "ttf", "sha256", "bin", "cfg",
              "ini", "csv", "orig", "jpg", "jpeg", "gif", "js", "ts", "db"}
TLDS = {"com", "org", "net", "io", "app", "co", "dev", "xyz", "ai", "gg", "info", "me", "us", "uk", "eu"}
SHELL_FENCES = {"bash", "sh", "shell", "console", "zsh"}
STREAMLIT_BUILTIN_PORT = 8501
CODE_SUFFIXES = {".py", ".sh", ".sol", ".toml", ".yml", ".yaml"}
SELF = {"tools/check_docs_paths.py", "tools/test_docs_paths.py"}  # their own literals would read every name

FENCE = re.compile(r"^\s*(`{3,}|~{3,})\s*([\w+-]*)")
CODE_SPAN = re.compile(r"(`+)(.+?)\1")
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
LINK = re.compile(r"!?\[(?:[^\[\]]|\[[^\]]*\])*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
IMG_SRC = re.compile(r"<img\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)[\"']", re.I)
HTML_ANCHOR = re.compile(r"<a\b[^>]*?\b(?:name|id)\s*=\s*[\"']([^\"']+)[\"']", re.I)
AUTOLINK = re.compile(r"<(?:https?|mailto):[^>]*>")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
PATH_TOKEN = re.compile(r"^[A-Za-z0-9_.@+-][A-Za-z0-9_.@+/-]*$")
EXT_SUFFIX = re.compile(r"^(.*?\.(?:%s))(?:[:#].*)?$" % "|".join(sorted(EXTENSIONS, key=len, reverse=True)))
LINE_SUFFIX = re.compile(r":\d+(?:-\d+)?$")

ENV_NAME = r"[A-Z][A-Z0-9_]*[A-Z0-9]"
ENV_ASSIGN = re.compile(r"(?:^|[\s;&|(]|\bexport\s+)(%s)=" % ENV_NAME)
ENV_DOLLAR = re.compile(r"\$\{?(%s)" % ENV_NAME)
ENV_BARE = re.compile(r"^%s$" % ENV_NAME)
ENV_CONTEXT = re.compile(r"\benv\b|\benvironment\b|\bvariables?\b|\.env\b|\bsecrets?\b", re.I)
CODE_QUOTED = re.compile(r"[\"'](%s)[\"']" % ENV_NAME)
CODE_SHELL = re.compile(r"\$\{?(%s)" % ENV_NAME)

HOSTS = r"(?:localhost|127\.0\.0\.1|0\.0\.0\.0)"
LOCAL_PORT = re.compile(HOSTS + r":(\d{2,5})\b")
SERVER_PORT = re.compile(r"--server\.port[= ]+[\"']?(\d{2,5})\b")
NAMED_PORT = re.compile(r"\b([A-Z_]*PORT)\b(?:\s*[=:]\s*|:-|`?\s*\|?\s*`?)(\d{4,5})\b")
BACKTICK_PORT = re.compile(r"`(\d{4,5})`")


@dataclass
class Finding:
    doc: str
    line: int
    kind: str
    value: str
    detail: str

    def render(self) -> str:
        return f"{self.doc}:{self.line}: {self.kind}: {self.value} — {self.detail}"


class SetupError(Exception):
    pass


# --- the repository, as git sees it ---------------------------------------------------------------------------

@dataclass
class Repo:
    root: Path
    files: set[str] = field(default_factory=set)
    dirs: set[str] = field(default_factory=set)
    gitlinks: set[str] = field(default_factory=set)
    basenames: set[str] = field(default_factory=set)
    _ignored: dict[str, bool] = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path) -> Repo:
        repo = cls(root)
        try:
            out = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "-z"], capture_output=True, check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise SetupError(f"git ls-files failed in {root}: {exc}") from exc
        for record in out.stdout.decode().split("\0"):
            if not record:
                continue
            meta, path = record.split("\t", 1)
            repo.files.add(path)
            repo.basenames.add(posixpath.basename(path))
            if meta.startswith("160000"):
                repo.gitlinks.add(path)
            parent = posixpath.dirname(path)
            while parent:
                repo.dirs.add(parent)
                parent = posixpath.dirname(parent)
        return repo

    def tracked(self, path: str) -> bool:
        path = path.rstrip("/")
        if path in self.files or path in self.dirs:
            return True
        return any(path.startswith(link + "/") for link in self.gitlinks)

    def is_file(self, path: str) -> bool:
        return path in self.files

    def ignored(self, path: str) -> bool:
        path = path.rstrip("/") or "."
        if path not in self._ignored:
            if path.startswith("../") or path == "..":
                self._ignored[path] = False
            else:
                # Also as a directory: a dir-only pattern (`cache/`, `.venv/`) cannot match a path that does not
                # exist yet, which is every generated directory in a fresh clone.
                self._ignored[path] = any(
                    subprocess.run(["git", "-C", str(self.root), "check-ignore", "-q", "--no-index", candidate],
                                   capture_output=True).returncode == 0
                    for candidate in (path, path + "/"))
        return self._ignored[path]

    def read(self, path: str) -> str:
        try:
            return (self.root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    def top_dirs(self) -> set[str]:
        return {d for d in self.dirs if "/" not in d} | {g for g in self.gitlinks if "/" not in g}


# --- a document, split into fences, code spans and prose ------------------------------------------------------

@dataclass
class Line:
    number: int
    text: str
    fence: str | None = None      # fence info string ("" for a bare fence) when inside one
    fence_start: int = 0
    table_env: bool = False       # inside a table whose header names variables


def parse(text: str) -> list[Line]:
    lines: list[Line] = []
    marker: str | None = None
    info, start = "", 0
    table_env = False
    for number, raw in enumerate(text.splitlines(), 1):
        match = FENCE.match(raw)
        if marker is None and match:
            marker, info, start = match.group(1), match.group(2).lower(), number
            lines.append(Line(number, raw))
            continue
        if marker is not None:
            stripped = raw.strip()
            if stripped.startswith(marker[0] * len(marker)) and not stripped.strip(marker[0]):
                marker = None
                lines.append(Line(number, raw))
            else:
                lines.append(Line(number, raw, fence=info, fence_start=start))
            continue
        if not raw.lstrip().startswith("|"):
            table_env = False
        elif not lines or not lines[-1].text.lstrip().startswith("|"):
            table_env = bool(re.search(r"\bvariables?\b|\benv\b", raw, re.I))  # the header row decides
        lines.append(Line(number, raw, table_env=table_env))
    return lines


def split_spans(text: str) -> tuple[list[str], str]:
    """(inline code spans, the prose left once spans are blanked out)."""
    spans = [m.group(2).strip() for m in CODE_SPAN.finditer(text)]
    return spans, CODE_SPAN.sub(" ", text)


def slugify(heading: str) -> str:
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", heading)
    text = re.sub(r"<[^>]+>", "", text).replace("`", "")
    text = re.sub(r"[^\w\- ]", "", text.strip().lower())
    return text.replace(" ", "-")


def anchors_of(text: str) -> set[str]:
    seen: dict[str, int] = {}
    anchors: set[str] = set()
    for line in parse(text):
        if line.fence is not None:
            continue
        anchors.update(m.group(1) for m in HTML_ANCHOR.finditer(line.text))
        match = HEADING.match(line.text)
        if not match:
            continue
        slug = slugify(match.group(2))
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        anchors.add(slug if count == 0 else f"{slug}-{count}")
    return anchors


# --- check a: paths -------------------------------------------------------------------------------------------

def remap_prefixes(repo: Repo) -> set[str]:
    prefixes = {"forge-std", "openzeppelin-contracts", "openzeppelin-contracts-upgradeable"}
    for line in repo.read("remappings.txt").splitlines():
        if "=" in line:
            prefixes.add(line.split("=", 1)[0].strip().rstrip("/").split("/")[0])
    return prefixes


def clean_token(token: str) -> str:
    token = token.strip("`'\"()[]{},;!?*")
    token = token.rstrip(".:")
    return token


def has_placeholder(token: str) -> bool:
    return any(mark in token for mark in ("<", ">", "{", "}", "*", "$", "…", "...", "%"))


def path_candidate(token: str, doc_dir: str, repo: Repo, remaps: set[str], code: bool) -> str | None:
    """The repo-relative path a token names, or None when it is not a path."""
    if not token or "://" in token or token.startswith(("/", "~", "#", "-")) or has_placeholder(token):
        return None
    if token == ".git" or token.startswith(".git/"):
        return None                                   # git's own directory: never tracked, never ignored
    match = EXT_SUFFIX.match(token)
    if match:
        token = match.group(1)
    token = LINE_SUFFIX.sub("", token).split("#", 1)[0]
    if not PATH_TOKEN.match(token) or token.startswith("@"):
        return None
    if re.fullmatch(r"[\d./]+", token):
        return None                                   # 1/2, 0.6, dates
    head = token.split("/", 1)[0]
    if head in remaps:
        return None
    if re.fullmatch(r"[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+", head) and head.rsplit(".", 1)[1].lower() in TLDS:
        return None                                   # host names: biorigdemo.streamlit.app, share.streamlit.io
    bare = token[2:] if token.startswith("./") else token
    ext = bare.rsplit(".", 1)[1].lower() if "." in posixpath.basename(bare.rstrip("/")) else ""
    if "/" in bare.rstrip("/"):
        first = bare.split("/", 1)[0]
        local = posixpath.normpath(posixpath.join(doc_dir, first)) if doc_dir else first
        if (ext in EXTENSIONS or token.startswith(("./", "../")) or first.startswith(".")
                or first in repo.top_dirs() or repo.tracked(local)):
            return bare
        return None
    name = bare.rstrip("/")
    if ext in EXTENSIONS and not name.startswith(".") and len(name.rsplit(".", 1)[0]) > 0:
        return bare
    if code and re.fullmatch(r"\.[A-Za-z][\w.-]*", name):
        if "." in name[1:] and ext in EXTENSIONS - {"example"}:
            return None                               # a suffix (`.normalized.json`), not a file
        return bare                                   # .env, .gitmodules, .env.example
    if code and bare.endswith("/") and name:
        return bare                                   # dashboard/
    return None


def resolve_path(path: str, doc_dir: str, repo: Repo) -> bool:
    candidates = [posixpath.normpath(path)]
    if doc_dir:
        candidates.append(posixpath.normpath(posixpath.join(doc_dir, path)))
    if any(repo.tracked(c) for c in candidates):
        return True
    if "/" not in path.rstrip("/") and path.rstrip("/") in repo.basenames:
        return True
    return any(repo.ignored(c) for c in candidates)


def tokens_of(text: str) -> list[str]:
    out: list[str] = []
    for raw in text.split():
        if has_placeholder(raw.strip("`'\"()[]{},;:!?")):
            out.append(raw)                           # kept whole so the placeholder still disqualifies it
            continue
        out.extend(part for part in re.split(r"[=,()\[\]'\"`|;&]+", raw) if part)
    return out


def check_paths(doc: str, lines: list[Line], repo: Repo) -> list[Finding]:
    doc_dir = posixpath.dirname(doc)
    remaps = remap_prefixes(repo)
    findings: list[Finding] = []

    def consider(raw: str, number: int, code: bool) -> None:
        if raw.startswith("*") and raw.rstrip(".,;:!?").endswith("*"):
            raw = raw.strip("*")                      # **bold** prose, not a glob
        elif has_placeholder(raw.strip("`'\"()[]{},;:!?")):
            return
        token = clean_token(raw)
        path = path_candidate(token, doc_dir, repo, remaps, code)
        if path and not resolve_path(path, doc_dir, repo):
            where = "the repo root" + (f" or {doc_dir}/" if doc_dir else "")
            findings.append(Finding(doc, number, "path", path, f"not tracked (from {where}) and not git-ignored"))

    for line in lines:
        if line.fence is not None:
            for token in tokens_of(line.text):
                consider(token, line.number, False)   # a bare `.name` in a fence is usually a jq filter
            continue
        if FENCE.match(line.text):
            continue
        text = AUTOLINK.sub(" ", IMG_SRC.sub(" ", line.text))
        text = LINK.sub(lambda m: m.group(0)[:m.group(0).rfind("](") + 1].lstrip("!"), text)  # keep link text
        spans, prose = split_spans(text)
        for span in spans:
            tokens = tokens_of(span)
            for token in tokens:
                consider(token, line.number, len(tokens) == 1)  # `.env` as a whole span names a file
        for token in prose.split():
            consider(token, line.number, False)
    return findings


# --- check b: links -------------------------------------------------------------------------------------------

def check_links(doc: str, lines: list[Line], repo: Repo) -> list[Finding]:
    doc_dir = posixpath.dirname(doc)
    findings: list[Finding] = []
    cache: dict[str, set[str]] = {}
    for line in lines:
        if line.fence is not None or FENCE.match(line.text):
            continue
        text = CODE_SPAN.sub(" ", line.text)
        targets = [m.group(1) for m in LINK.finditer(text)] + [m.group(1) for m in IMG_SRC.finditer(text)]
        for target in targets:
            if SCHEME.match(target) or target.startswith("//"):
                continue
            path, _, anchor = target.partition("#")
            if path:
                resolved = posixpath.normpath(path[1:] if path.startswith("/") else posixpath.join(doc_dir, path))
                if not repo.tracked(resolved):
                    findings.append(Finding(doc, line.number, "link", target, f"{resolved} is not tracked"))
                    continue
            else:
                resolved = doc
            if anchor and resolved.endswith(".md") and repo.is_file(resolved):
                if resolved not in cache:
                    cache[resolved] = anchors_of(repo.read(resolved))
                if anchor not in cache[resolved]:
                    findings.append(Finding(doc, line.number, "link", target,
                                            f"no heading in {resolved} has the slug #{anchor}"))
    return findings


# --- check c: commands ----------------------------------------------------------------------------------------

def shell_commands(lines: list[Line], console: bool) -> list[tuple[int, str]]:
    """(first line number, command text) with continuations joined; console fences keep only `$ ` lines."""
    out: list[tuple[int, str]] = []
    pending, start = "", 0
    for line in lines:
        text = line.text.strip()
        if not pending:
            if console:
                if not text.startswith("$ "):
                    continue                          # output, not a command
                text = text[2:]
            start = line.number
        if text.endswith("\\"):
            pending += text[:-1] + " "
            continue
        out.append((start, pending + text))
        pending = ""
    if pending:
        out.append((start, pending))
    return out


def shell_split(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()")
    lexer.whitespace_split = True
    lexer.commenters = "#"
    try:
        return list(lexer)
    except ValueError:
        return command.split("#", 1)[0].split()


def segments(tokens: list[str]) -> list[list[str]]:
    out: list[list[str]] = [[]]
    for token in tokens:
        if token and set(token) <= set(";&|()"):
            out.append([])
        else:
            out[-1].append(token)
    return [s for s in out if s]


def check_commands(doc: str, lines: list[Line], repo: Repo) -> list[Finding]:
    findings: list[Finding] = []
    fences: dict[int, list[Line]] = {}
    for line in lines:
        if line.fence in SHELL_FENCES:
            fences.setdefault(line.fence_start, []).append(line)
    top = repo.top_dirs()

    def need(number: int, token: str, path: str, why: str) -> None:
        if repo.tracked(path):
            return
        state = "git-ignored, so absent from a clean clone" if repo.ignored(path) else "not tracked"
        findings.append(Finding(doc, number, "command", token, f"{why} {path}: {state}"))

    for body in fences.values():
        cwd: str | None = ""
        for number, command in shell_commands(body, body[0].fence == "console"):
            for seg in segments(shell_split(command)):
                while seg and re.fullmatch(r"%s=.*" % ENV_NAME, seg[0]):
                    seg = seg[1:]
                if not seg:
                    continue
                if seg[0] == "cd":
                    target = posixpath.normpath(posixpath.join(cwd or "", seg[1])) if len(seg) > 1 else ""
                    cwd = target if cwd is not None and repo.tracked(target) else None
                    continue
                if cwd is None:
                    continue                          # cd'd somewhere the repo does not describe
                exe = posixpath.basename(seg[0])
                for i, token in enumerate(seg):
                    if has_placeholder(token):
                        continue
                    prev = seg[i - 1] if i else ""
                    if prev == "-m" and exe.startswith("python"):
                        top_pkg = token.split(".", 1)[0]
                        if top_pkg in top:
                            mod = token.replace(".", "/")
                            base = posixpath.join(cwd, mod)
                            if not (repo.is_file(base + ".py") or repo.is_file(base + "/__main__.py")):
                                findings.append(Finding(doc, number, "command", f"-m {token}",
                                                        f"neither {base}.py nor {base}/__main__.py is tracked"))
                        continue
                    if prev == "-r" and "pip" in exe:
                        need(number, token, posixpath.normpath(posixpath.join(cwd, token)), "requirements file")
                        continue
                    if token.startswith(".venv/") or token.startswith("-"):
                        continue
                    stripped = token[2:] if token.startswith("./") else token
                    match = EXT_SUFFIX.match(stripped)
                    if match:
                        stripped = match.group(1)
                    if (stripped.endswith((".sh", ".py")) or token.startswith("./")
                            or stripped.startswith(("scripts/", "script/", "tools/"))):
                        if "://" in stripped or stripped.startswith("/"):
                            continue
                        need(number, token, posixpath.normpath(posixpath.join(cwd, stripped)), "names")
    return findings


# --- check d: ports -------------------------------------------------------------------------------------------

@dataclass
class Ports:
    streamlit: int
    streamlit_source: str
    gate: int | None
    relay: int | None
    named: dict[int, str]                             # every known default -> where it comes from


def code_ports(repo: Repo) -> Ports:
    streamlit, source = STREAMLIT_BUILTIN_PORT, "Streamlit's built-in default"
    for config in (".streamlit/config.toml", "dashboard/.streamlit/config.toml"):
        if repo.is_file(config):
            try:
                port = tomllib.loads(repo.read(config)).get("server", {}).get("port")
            except tomllib.TOMLDecodeError:
                port = None
            if isinstance(port, int):
                streamlit, source = port, f"[server] port in {config}"
            elif source.startswith("Streamlit"):
                source = f"Streamlit's built-in default ({config} sets no [server] port)"
    named: dict[int, str] = {streamlit: f"streamlit, {source}"}
    match = re.search(r"\bPORT=\$\{DEMO_PORT:-(\d+)\}", repo.read("scripts/verify-demo.sh"))
    gate = int(match.group(1)) if match else None
    if gate:
        named[gate] = "the DEMO_PORT default in scripts/verify-demo.sh"
    match = re.search(r"\"RELAY_PORT\"\s*,\s*(\d+)", repo.read("relay/config.py"))
    relay = int(match.group(1)) if match else None
    if relay:
        named[relay] = "the RELAY_PORT default in relay/config.py"
    match = re.search(r"\bPORT\b\D{0,40}?(\d{4,5})", repo.read("dashboard/config.py"))
    if match:
        named.setdefault(int(match.group(1)), "dashboard/config.py")
    for path in sorted(p for p in repo.files if p.endswith(".sh") and not p.startswith("lib/")):
        for name, value in re.findall(r"\$\{(\w*PORT\w*):-(\d{2,5})\}", repo.read(path)):
            named.setdefault(int(value), f"the {name} default in {path}")
    hosted = "scripts/check-hosted-entrypoint.py"
    for value in re.findall(r"(?:boot\(\s*\w+\s*,\s*|\bport\s*=\s*)(\d{4,5})", repo.read(hosted)):
        named.setdefault(int(value), f"a port {hosted} boots on")
    return Ports(streamlit, source, gate, relay, named)


def check_ports(doc: str, lines: list[Line], repo: Repo, ports: Ports) -> list[Finding]:
    findings: list[Finding] = []
    for line in lines:
        text = line.text
        reported: set[int] = set()

        def flag(value: int, detail: str) -> None:
            if value not in reported:
                reported.add(value)
                findings.append(Finding(doc, line.number, "port", str(value), detail))

        named = [(n, int(v)) for n, v in NAMED_PORT.findall(text)]
        local = [int(v) for v in LOCAL_PORT.findall(text)]
        explicit = {int(v) for v in SERVER_PORT.findall(text)}
        loose = [int(v) for v in BACKTICK_PORT.findall(text)]
        if "DEMO_PORT" in text and ports.gate:
            values = [v for n, v in named if n == "DEMO_PORT"] or local or loose
            for value in values:
                if value != ports.gate:
                    flag(value, f"contradicts the gate default DEMO_PORT={ports.gate} in scripts/verify-demo.sh")
            continue
        if ("RELAY_PORT" in text or re.search(r"-m relay\b(?!\.)", text)) and ports.relay:
            values = [v for n, v in named if n == "RELAY_PORT"] + local
            if "RELAY_PORT" in text:
                values += loose
            for value in values:
                if value != ports.relay:
                    flag(value, f"contradicts the relay default RELAY_PORT={ports.relay} in relay/config.py")
            continue
        if re.search(r"streamlit|dashboard", text, re.I) and (local or explicit):
            allowed = {ports.streamlit} | explicit
            for value in local:
                if value not in allowed:
                    flag(value, f"contradicts the streamlit port {ports.streamlit} ({ports.streamlit_source})")
            continue
        for value in local:
            if value not in ports.named:
                known = ", ".join(f"{p} ({w})" for p, w in sorted(ports.named.items()))
                flag(value, f"matches no default the code sets; known: {known}")
    return findings


# --- check e: env vars ----------------------------------------------------------------------------------------

def code_env_reads(repo: Repo) -> set[str]:
    names: set[str] = set()
    for path in repo.files:
        if path.startswith("lib/") or path in SELF:
            continue
        # A suffix-less tracked file with a shell shebang (scripts/git-hooks/pre-push) is shell code too.
        hook = not Path(path).suffix and repo.is_file(path) and repo.read(path).startswith("#!/usr/bin/env bash")
        if Path(path).suffix not in CODE_SUFFIXES and not hook:
            continue
        text = repo.read(path)
        names.update(CODE_QUOTED.findall(text))
        if path.endswith(".sh") or hook:
            names.update(CODE_SHELL.findall(text))
    return names


def template_keys(repo: Repo) -> set[str]:
    keys: set[str] = set()
    for path in (".env.example", ".env.mainnet.example"):
        if repo.is_file(path):
            keys.update(re.findall(r"^\s*(?:export\s+)?(%s)=" % ENV_NAME, repo.read(path), re.M))
    return keys


def shell_locals(lines: list[Line]) -> dict[int, set[str]]:
    """Per shell fence, the names it sets as plain shell variables: `NAME=value` alone on a command, unexported,
    or a `for NAME in` loop. Those are the fence's own scratch values, not environment the code reads."""
    fences: dict[int, list[Line]] = {}
    for line in lines:
        if line.fence in SHELL_FENCES:
            fences.setdefault(line.fence_start, []).append(line)
    out: dict[int, set[str]] = {}
    for start, body in fences.items():
        names: set[str] = set()
        for _, command in shell_commands(body, body[0].fence == "console"):
            for seg in segments(shell_split(command)):
                if all(re.fullmatch(r"%s=.*" % ENV_NAME, token) for token in seg):
                    names.update(token.split("=", 1)[0] for token in seg)
                if len(seg) > 2 and seg[0] == "for" and seg[2] == "in":
                    names.add(seg[1])
        out[start] = names
    return out


def doc_env_names(lines: list[Line], keys: set[str]) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    scratch = shell_locals(lines)
    for line in lines:
        if line.fence is not None:
            if line.fence in SHELL_FENCES or line.fence in ("", "env", "dotenv"):
                code = re.sub(r"(^|\s)#.*$", "", line.text)  # a name in a comment is prose
                local = scratch.get(line.fence_start, set())
                found += [(line.number, n) for n in ENV_ASSIGN.findall(code) + ENV_DOLLAR.findall(code)
                          if n not in local]
            continue
        spans, _ = split_spans(line.text)
        context = bool(ENV_CONTEXT.search(line.text)) or line.table_env
        for span in spans:
            found += [(line.number, n) for n in ENV_ASSIGN.findall(span) + ENV_DOLLAR.findall(span)]
            if ENV_BARE.match(span) and (span in keys or context) and not span.endswith("_ROLE"):
                found.append((line.number, span))     # the whole span is the name: `POST /v1/x` is not
    return found


def check_env(doc: str, lines: list[Line], repo: Repo, reads: set[str], keys: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    for number, name in doc_env_names(lines, keys):
        if name not in reads:
            findings.append(Finding(doc, number, "env", name, "no tracked code reads this variable"))
    return findings


# --- check f: submodules --------------------------------------------------------------------------------------

def check_submodules(doc: str, lines: list[Line], repo: Repo) -> list[Finding]:
    if doc != "README.md" or not repo.is_file(".gitmodules"):
        return []
    modules = re.findall(r"^\s*path\s*=\s*(\S+)", repo.read(".gitmodules"), re.M)
    in_section, fence_line, body = False, 0, []
    for line in lines:
        if line.fence is None and not FENCE.match(line.text):
            match = HEADING.match(line.text)
            if match:
                if fence_line:
                    break
                in_section = len(match.group(1)) == 2 and slugify(match.group(2)) == "quick-start"
            continue
        if in_section and line.fence in SHELL_FENCES:
            if fence_line and line.fence_start != fence_line:
                break
            fence_line = line.fence_start
            body.append(line.text)
    joined = "\n".join(body)
    if re.search(r"git\s+submodule\s+update\b[^\n#]*--init|git\s+clone\b[^\n#]*--recurse-submodules", joined):
        return []
    names = ", ".join(modules) or "submodules"
    if not fence_line:
        return [Finding(doc, 1, "submodule", "Quick start",
                        f"no `## Quick start` bash fence to initialise the .gitmodules submodules ({names})")]
    return [Finding(doc, fence_line, "submodule", "Quick start",
                    f".gitmodules declares {len(modules)} submodules ({names}) but this fence has no "
                    "`git submodule update --init --recursive` or `git clone --recurse-submodules`")]


# --- allowlist ------------------------------------------------------------------------------------------------

@dataclass
class Allow:
    kind: str
    value: str
    reason: str
    doc: str | None
    line: int
    used: bool = False

    def matches(self, finding: Finding) -> bool:
        return (self.kind == finding.kind and self.value == finding.value
                and (self.doc is None or self.doc == finding.doc))


def load_allowlist(path: Path, label: str) -> list[Allow]:
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        raise SetupError(f"allowlist {label}: {exc}") from exc
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise SetupError(f"allowlist {label}: expected {{\"entries\": [...]}}")
    out: list[Allow] = []
    for i, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            raise SetupError(f"allowlist {label}: entry {i} is not an object")
        kind, value, reason = entry.get("kind"), entry.get("value"), entry.get("reason")
        if kind not in KINDS:
            raise SetupError(f"allowlist {label}: entry {i} has kind {kind!r}, expected one of {', '.join(KINDS)}")
        if not isinstance(value, str) or not value:
            raise SetupError(f"allowlist {label}: entry {i} has no value")
        if not isinstance(reason, str) or not reason.strip():
            raise SetupError(f"allowlist {label}: entry {i} ({kind} {value}) has no reason")
        doc = entry.get("doc")
        if doc is not None and not isinstance(doc, str):
            raise SetupError(f"allowlist {label}: entry {i} has a non-string doc")
        needle = json.dumps(value)
        line = next((n for n, raw in enumerate(text.splitlines(), 1) if needle in raw), 1)
        out.append(Allow(kind, value, reason.strip(), doc, line))
    return out


# --- driver ---------------------------------------------------------------------------------------------------

def run(root: Path, docs: list[str], allow: list[Allow], default_set: bool, allow_label: str
        ) -> tuple[list[Finding], int]:
    repo = Repo.load(root)
    ports = code_ports(repo)
    reads = code_env_reads(repo)
    keys = template_keys(repo)
    raw: list[Finding] = []
    for doc in docs:
        if not repo.is_file(doc):
            raw.append(Finding(doc, 1, "doc", doc, "not tracked by git, so not checked"))
            continue
        lines = parse(repo.read(doc))
        raw += check_paths(doc, lines, repo)
        raw += check_links(doc, lines, repo)
        raw += check_commands(doc, lines, repo)
        raw += check_ports(doc, lines, repo, ports)
        raw += check_env(doc, lines, repo, reads, keys)
        raw += check_submodules(doc, lines, repo)
    findings: list[Finding] = []
    seen: set[tuple[str, int, str, str]] = set()
    suppressed = 0
    for finding in raw:
        key = (finding.doc, finding.line, finding.kind, finding.value)
        if key in seen:
            continue
        seen.add(key)
        hits = [entry for entry in allow if entry.matches(finding)]
        for entry in hits:
            entry.used = True
        if hits:
            suppressed += 1
        else:
            findings.append(finding)
    if default_set:
        for entry in allow:
            if not entry.used:
                scope = f" in {entry.doc}" if entry.doc else ""
                findings.append(Finding(allow_label, entry.line, "allowlist", entry.value,
                                        f"{entry.kind} entry{scope} matched nothing; remove it"))
    return findings, suppressed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--docs", nargs="+", help=f"documents to check (default: {' '.join(DEFAULT_DOCS)})")
    parser.add_argument("--allow", help=f"allowlist, relative to the repo root (default: {DEFAULT_ALLOW})")
    parser.add_argument("--json", action="store_true", help="one JSON report on stdout")
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    docs = [posixpath.normpath(d) for d in args.docs] if args.docs else list(DEFAULT_DOCS)
    allow_label = args.allow or DEFAULT_ALLOW
    allow_path = Path(allow_label) if Path(allow_label).is_absolute() else root / allow_label
    try:
        if args.allow or allow_path.exists():
            allow = load_allowlist(allow_path, allow_label)
        else:
            allow = []
        findings, suppressed = run(root, docs, allow, not args.docs, allow_label)
    except SetupError as exc:
        print(f"setup error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"docs": docs, "findings": [asdict(f) for f in findings], "suppressed": suppressed,
                          "ok": not findings}, indent=2))
    else:
        print(f"checked {len(docs)} documents: {' '.join(docs)}")
        for finding in findings:
            print(finding.render())
        status = f"{len(findings)} finding(s)" if findings else "clean"
        print(f"{status}; {suppressed} allowlisted")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
