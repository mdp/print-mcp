#!/usr/bin/env python3
"""Phase 1 CLI: render a Markdown file to PDF and submit it to a CUPS printer.

Runs inside the project's `server` Docker image (has weasyprint + pycups).
Talks to the dockerized CUPS service over the compose network.

Examples:
    print_file.py notes.md
    print_file.py notes.md --printer brother-hl2350dw --page-size a4 --copies 2
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

from print_mcp.config import Settings
from print_mcp.errors import PrintMcpError
from print_mcp.models import ColorMode, Orientation, PageMargins, PageSize, Sides
from print_mcp.printer import CupsPrinter
from print_mcp.render import render_markdown_pdf

SIZE_ALIASES = {
    "letter": PageSize.LETTER,
    "legal": PageSize.LEGAL,
    "a4": PageSize.A4,
}
COLOR_ALIASES = {
    "auto": ColorMode.AUTO,
    "color": ColorMode.COLOR,
    "mono": ColorMode.MONOCHROME,
    "monochrome": ColorMode.MONOCHROME,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Markdown to PDF and print it via CUPS.")
    parser.add_argument(
        "file", type=Path, help="path to the input Markdown file, or '-' to read stdin"
    )
    parser.add_argument("--printer", help="CUPS queue name (default: settings/default queue)")
    parser.add_argument("--title", help="job title (default: file name)")
    parser.add_argument("--page-size", default="letter", choices=sorted(SIZE_ALIASES))
    parser.add_argument("--orientation", default="portrait", choices=["portrait", "landscape"])
    parser.add_argument("--margins-mm", type=float, help="uniform page margins in mm")
    parser.add_argument("--copies", type=int, default=1)
    sides_choices = ["one-sided", "two-sided-long-edge", "two-sided-short-edge"]
    parser.add_argument("--sides", default="two-sided-long-edge", choices=sides_choices)
    parser.add_argument("--color", default="auto", choices=sorted(COLOR_ALIASES))
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    settings = Settings()
    from_stdin = str(args.file) == "-"
    if not from_stdin and not args.file.exists():
        print(f"error: no such file: {args.file}", file=sys.stderr)
        return 2

    orientation = Orientation.LANDSCAPE if args.orientation == "landscape" else Orientation.PORTRAIT
    margin = args.margins_mm or settings.default_margin_mm
    margins = PageMargins(top=margin, right=margin, bottom=margin, left=margin)

    if from_stdin:
        markdown = sys.stdin.read()
        title = args.title or "stdin"
        destination = Path(tempfile.gettempdir()) / f"{title or 'print'}.pdf"
    else:
        markdown = args.file.read_text(encoding="utf-8")
        title = args.title or args.file.stem
        destination = args.file.parent / f"{args.file.stem}.pdf"

    rendered = await render_markdown_pdf(
        markdown,
        destination,
        settings,
        SIZE_ALIASES[args.page_size],
        orientation,
        margins,
    )
    print(f"rendered {rendered.path} ({rendered.page_count} pages)")

    job_id, printer = await CupsPrinter(settings).submit(
        rendered.path,
        args.printer,
        title,
        SIZE_ALIASES[args.page_size],
        args.copies,
        Sides(args.sides),
        COLOR_ALIASES[args.color],
    )
    print(f"submitted job {job_id} to printer {printer!r}")
    return 0


def main() -> int:
    try:
        return asyncio.run(run(parse_args()))
    except PrintMcpError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI top-level handler
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())