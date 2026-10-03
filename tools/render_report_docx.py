#!/usr/bin/env python3
"""Render docs/milestone-roadmap-report.md, the project milestone and roadmap report, to a .docx.

The report is set exactly as the grant proposal is: this script loads tools/render_proposal_docx.py by its
path, so the parser, cover, contents, running header, footer, palette and metadata are that renderer's and
the two documents cannot drift apart in look. Only what names the document changes: the cover subtitle, the
footer title, and the title, subject and category in the package metadata. tools/render_proposal_docx.py
itself is not modified.

The same checks the proposal renderer applies run here: every heading appears in the rendered text, every
internal link resolves to a heading, and the package's authorship metadata names Adam Jannoud. One more is
added for the report, which is mostly tables: every pipe table in the markdown must come out as a real
table in the document, found by its header row, not as paragraphs of pipes.

Usage:
    .venv/bin/python tools/render_report_docx.py --src docs/milestone-roadmap-report.md --out PATH
"""

from __future__ import annotations

import argparse
import importlib.util
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent

SUBTITLE = "Complete project audit, live verification sweep and forward roadmap"
FOOTER_TITLE = "BioRig — Project Milestone and Roadmap Report"
TITLE = "BioRig — Project Milestone and Roadmap Report"
SUBJECT = "Project audit, live verification sweep and forward roadmap"
CATEGORY = "Project report"

# A pipe table is a header row followed by a delimiter row such as `| --- | :---: |`.
TABLE_DELIMITER = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def load_proposal_renderer():
    """Import tools/render_proposal_docx.py by path, so this works from any working directory."""
    path = HERE / "render_proposal_docx.py"
    spec = importlib.util.spec_from_file_location("render_proposal_docx", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def name_the_report(renderer) -> None:
    """Point the cover, footer and metadata at the report instead of the proposal."""
    renderer.SUBTITLE = SUBTITLE
    renderer.FOOTER_TITLE = FOOTER_TITLE
    proposal_properties = renderer.set_properties

    def set_properties(document, source: pathlib.Path) -> None:
        proposal_properties(document, source)  # author, keywords, field refresh: the proposal's own
        properties = document.core_properties
        properties.title, properties.subject, properties.category = TITLE, SUBJECT, CATEGORY
        properties.comments = (f"Rendered from {source.name} by tools/render_report_docx.py through "
                               "tools/render_proposal_docx.py. The Markdown is the source of truth.")

    renderer.set_properties = set_properties


def markdown_table_headers(text: str) -> list[list[str]]:
    """The header row of every pipe table in the markdown, fenced code skipped, as normalised cell texts."""
    headers, fenced, previous = [], False, ""
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        elif not fenced and TABLE_DELIMITER.match(line) and previous.lstrip().startswith("|"):
            headers.append([_norm(cell) for cell in previous.strip().strip("|").split("|")])
        previous = "" if fenced else line
    return headers


def _norm(text: str) -> str:
    """Compare cell text without markdown emphasis, code ticks or spacing."""
    return re.sub(r"[^0-9A-Za-z]+", "", text)


def tables_not_rendered(source: pathlib.Path, docx_path: pathlib.Path) -> list[list[str]]:
    """Markdown tables with no matching table in the document, matched in order by their header row.

    The document holds more tables than the markdown: the cover's field block and its callout are tables
    too. So each markdown table must find its own header among the document's tables, in order.
    """
    from docx import Document

    rendered = [[_norm(cell.text) for cell in table.rows[0].cells] for table in Document(docx_path).tables]
    missing, position = [], 0
    for header in markdown_table_headers(source.read_text(encoding="utf-8")):
        found = next((i for i in range(position, len(rendered)) if rendered[i] == header), None)
        if found is None:
            missing.append(header)        # keep the position, so one miss does not hide the tables after it
        else:
            position = found + 1
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--src", default=str(REPO / "docs/milestone-roadmap-report.md"),
                        help="the report markdown (default: docs/milestone-roadmap-report.md)")
    parser.add_argument("--out", required=True, help="where to write the .docx")
    args = parser.parse_args()
    source, destination = pathlib.Path(args.src), pathlib.Path(args.out)

    renderer = load_proposal_renderer()
    name_the_report(renderer)

    report = renderer.render(source, destination)
    expected = len(markdown_table_headers(source.read_text(encoding="utf-8")))
    for key in ("path", "bytes", "paragraphs", "tables", "headings", "internal_links", "external_links"):
        print(f"{key}: {report[key]}")
    print(f"markdown_tables: {expected}")

    problems: list[str] = []
    if report["missing_headings"]:
        problems.append(f"headings missing from the rendered text: {report['missing_headings']}")
    if report["unresolved_anchors"]:
        problems.append(f"internal links pointing at no heading: {report['unresolved_anchors']}")
    for header in tables_not_rendered(source, destination):
        problems.append(f"a markdown table did not render as a table (header {header})")
    problems += renderer.attribution_problems(destination)
    for problem in problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
