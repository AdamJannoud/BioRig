#!/usr/bin/env python3
"""Render docs/prezenti-proposal.md to a print-quality A4 PDF.

The Markdown stays the single source of truth: this script only decides chrome
(title block, contents page, running footer) and print typography. Links are
kept live, so the internal "Section N" references jump within the PDF and the
explorer links open from the reader.

Usage:
    python3 tools/render_proposal_pdf.py [--src PATH] [--out PATH] [--check]
"""

from __future__ import annotations

import argparse
import html
import pathlib
import re
import sys

import markdown

REPO = pathlib.Path(__file__).resolve().parents[1]

FIELD = re.compile(r"^\*\*(?P<label>[^*]+?):\*\*\s*(?P<value>.*)$")
HEADING = re.compile(r"<h(?P<level>[23])[^>]*>(?P<text>.*?)</h(?P=level)>", re.S)
ANCHOR = re.compile(r'href="#(?P<id>[^"]+)"')
ID = re.compile(r'id="(?P<id>[^"]+)"')

FOOTER = """
<div style="width:100%;font-family:Lato,Arial,sans-serif;font-size:7.6pt;color:#7d8a96;
            padding:0 2mm;border-top:0.6pt solid #dde3e9;">
  <div style="display:flex;justify-content:space-between;padding-top:2.4mm;">
    <span>BioRig &mdash; Prezenti Grant Application Proposal</span>
    <span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span>
  </div>
</div>
"""


def split_document(text: str) -> tuple[str, str]:
    """Return (header Markdown, body Markdown), split at the first `## ` heading."""
    match = re.search(r"^## ", text, re.M)
    if not match:
        raise ValueError("no level-2 heading found; nothing to split the title block from")
    return text[: match.start()], text[match.start() :]


def inline(fragment: str, md: markdown.Markdown) -> str:
    """Render one line of inline Markdown without wrapping it in a paragraph."""
    rendered = markdown.markdown(fragment, extensions=["extra"])
    return re.sub(r"^<p>|</p>$", "", rendered.strip())


def build_title_block(header_md: str, md: markdown.Markdown) -> str:
    lines = header_md.splitlines()
    title = lines[0].lstrip("#").strip()

    rows: list[str] = []
    callout: list[str] = []
    for raw in lines[1:]:
        line = raw.strip()
        if not line or line == "---":
            continue
        if line.startswith(">"):
            callout.append(line.lstrip("> ").strip())
            continue
        field = FIELD.match(line)
        if not field:
            raise ValueError(f"title-block line is neither a meta field nor a quote: {line!r}")
        rows.append(
            "<tr><td class='k'>{}</td><td>{}</td></tr>".format(
                html.escape(field.group("label")),
                inline(field.group("value"), md),
            )
        )

    parts = [
        "<section class='title-block'>",
        "<p class='eyebrow'>Prezenti Grants &middot; Celo Community Grants</p>",
        f"<h1 class='doc-title'>{inline(title, md)}</h1>",
        "<p class='doc-subtitle'>Prepared for the Prezenti review team &middot; 1 October 2026</p>",
        "<table class='meta'>",
        "".join(rows),
        "</table>",
    ]
    if callout:
        parts.append("<div class='callout'>{}</div>".format(inline(" ".join(callout), md)))
    parts.append("</section>")
    return "\n".join(parts)


def build_toc(body_html: str) -> str:
    entries: list[str] = []
    for match in HEADING.finditer(body_html):
        level, text = match.group("level"), match.group("text")
        if "toc-title" in text:
            continue
        anchor = re.search(r'id="([^"]+)"', match.group(0))
        if not anchor:
            continue
        entries.append(
            "<li class='lvl{l}'><a href='#{a}'>{t}</a></li>".format(
                l=level, a=anchor.group(1), t=re.sub(r"<[^>]+>", "", text)
            )
        )
    return "<ul>{}</ul>".format("".join(entries))


def assert_links_resolve(body_html: str) -> None:
    ids = set(ID.findall(body_html))
    broken = sorted({href for href in ANCHOR.findall(body_html) if href not in ids})
    if broken:
        raise ValueError(f"internal links with no target: {broken}")


def set_metadata(path: pathlib.Path) -> None:
    """Stamp document properties. Chromium writes only a Title, and a submission
    PDF should name its author when a reviewer opens the properties panel."""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(path))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.add_metadata(
        {
            "/Title": "BioRig - Prezenti Grant Application Proposal",
            "/Author": "Adam Jannoud",
            "/Subject": (
                "Prezenti Grants (Celo Community Grants) application: BioRig, mobile-first dMRV "
                "and proof-of-growth infrastructure on Celo"
            ),
            "/Keywords": (
                "BioRig, Celo, Prezenti, dMRV, agroforestry, ERC-721, ERC-6551, H3, proof-of-growth"
            ),
            "/Creator": "tools/render_proposal_pdf.py",
        }
    )
    stamped = path.with_suffix(".stamped.pdf")
    with stamped.open("wb") as handle:
        writer.write(handle)
    stamped.replace(path)


def report(path: pathlib.Path) -> None:
    """Print the facts a reviewer would check, so the run is self-verifying."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    external = internal = 0
    for page in reader.pages:
        for annot in page.get("/Annots") or []:
            obj = annot.get_object()
            if obj.get("/Subtype") != "/Link":
                continue
            if (obj.get("/A") or {}).get("/URI"):
                external += 1
            else:
                internal += 1
    print(f"pages: {len(reader.pages)} | external links: {external} | internal links: {internal}")
    print(f"title: {reader.metadata.get('/Title')} | author: {reader.metadata.get('/Author')}")


def render(source: pathlib.Path, output: pathlib.Path, css: pathlib.Path) -> pathlib.Path:
    from playwright.sync_api import sync_playwright

    md = markdown.Markdown(extensions=["extra", "sane_lists", "toc"], extension_configs={"toc": {"permalink": False}})
    header_md, body_md = split_document(source.read_text(encoding="utf-8"))

    body_html = md.convert(body_md)
    assert_links_resolve(body_html)

    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>BioRig &mdash; Prezenti Grant Application Proposal</title>
<style>{css.read_text(encoding="utf-8")}</style>
</head><body>
{build_title_block(header_md, markdown.Markdown(extensions=["extra"]))}
<section class="toc"><h2 class="toc-title">Contents</h2>
{build_toc(body_html)}
</section>
{body_html}
</body></html>"""

    output.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(java_script_enabled=False)
        pdf_page = context.new_page()
        pdf_page.set_content(page, wait_until="load")
        pdf_page.emulate_media(media="print")
        pdf_page.pdf(
            path=str(output),
            format="A4",
            print_background=True,
            display_header_footer=True,
            header_template="<div></div>",
            footer_template=FOOTER,
            margin={"top": "17mm", "bottom": "17mm", "left": "17mm", "right": "17mm"},
        )
        browser.close()
    set_metadata(output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", default=str(REPO / "docs/prezenti-proposal.md"))
    parser.add_argument("--out", default=str(REPO / "out/proposal/BioRig-Prezenti-Grant-Application-Proposal.pdf"))
    parser.add_argument("--css", default=str(REPO / "tools/print/proposal.css"))
    args = parser.parse_args()

    result = render(pathlib.Path(args.src), pathlib.Path(args.out), pathlib.Path(args.css))
    print(f"rendered {result} ({result.stat().st_size:,} bytes)")
    report(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
