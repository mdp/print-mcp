from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from .config import Settings
from .errors import PrintMcpError
from .models import (
    ColorMode,
    JobInfo,
    Orientation,
    PageMargins,
    PageSize,
    PrinterInfo,
    PrintResult,
    Sides,
)
from .printer import CupsPrinter
from .render import render_markdown_pdf


def create_mcp(settings: Settings, printer: CupsPrinter | None = None) -> FastMCP:
    mcp = FastMCP(
        "Markdown Printer",
        instructions=(
            "Print Markdown documents through the configured CUPS queue. "
            "Printing consumes physical resources and is not reversible."
        ),
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=settings.allowed_hosts,
            allowed_origins=list(settings.allowed_origins),
        ),
    )
    cups_printer = printer or CupsPrinter(settings)
    render_slots = asyncio.Semaphore(settings.max_concurrent_renders)

    @mcp.tool(
        annotations={
            "title": "Print Markdown",
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        }
    )
    async def print_markdown(
        markdown: str,
        title: str = "Markdown document",
        printer: str | None = None,
        page_size: PageSize | None = None,
        orientation: Orientation = Orientation.PORTRAIT,
        margins: PageMargins | None = None,
        copies: int = 1,
        sides: Sides = Sides.LONG_EDGE,
        color_mode: ColorMode = ColorMode.AUTO,
    ) -> PrintResult:
        """Render Markdown as a polished PDF and submit it to the configured printer."""
        if not 1 <= copies <= 10:
            raise ToolError("INVALID_INPUT: copies must be between 1 and 10")
        chosen_size = page_size or PageSize(settings.default_page_size)
        chosen_margins = margins or PageMargins(
            top=settings.default_margin_mm,
            right=settings.default_margin_mm,
            bottom=settings.default_margin_mm,
            left=settings.default_margin_mm,
        )
        try:
            async with render_slots:
                with tempfile.TemporaryDirectory(prefix="print-mcp-") as temporary:
                    pdf_path = Path(temporary) / "document.pdf"
                    rendered = await render_markdown_pdf(
                        markdown,
                        pdf_path,
                        settings,
                        chosen_size,
                        orientation,
                        chosen_margins,
                    )
                    job_id, chosen_printer = await cups_printer.submit(
                        rendered.path,
                        printer,
                        title[:255],
                        chosen_size,
                        copies,
                        sides,
                        color_mode,
                    )
            return PrintResult(
                job_id=job_id,
                printer=chosen_printer,
                title=title[:255],
                page_count=rendered.page_count,
                state="pending",
            )
        except PrintMcpError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool(annotations={"title": "List Printers", "readOnlyHint": True})
    async def list_printers() -> list[PrinterInfo]:
        """Report the configured CUPS printer and its current capabilities."""
        return await cups_printer.list_printers()

    @mcp.tool(annotations={"title": "Get Print Job Status", "readOnlyHint": True})
    async def get_job_status(job_id: int) -> JobInfo:
        """Get the current state of a CUPS print job."""
        try:
            return await cups_printer.get_job(job_id)
        except PrintMcpError as exc:
            raise ToolError(str(exc)) from exc

    return mcp
