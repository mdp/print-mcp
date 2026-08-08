from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .config import Settings
from .errors import JobNotFound, PrinterUnavailable, SubmissionFailed, UnsupportedOption
from .models import ColorMode, JobInfo, PageSize, PrinterInfo, Sides

PRINTER_STATES = {3: "idle", 4: "processing", 5: "stopped"}
JOB_STATES = {
    3: "pending",
    4: "pending-held",
    5: "processing",
    6: "processing-stopped",
    7: "canceled",
    8: "aborted",
    9: "completed",
}
MEDIA_OPTIONS = {PageSize.LETTER: "Letter", PageSize.LEGAL: "Legal", PageSize.A4: "A4"}


def _cups():
    try:
        import cups
    except ImportError as exc:
        raise PrinterUnavailable("the CUPS client library is not installed") from exc
    return cups


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [str(value)]


def redact_uri(uri: str) -> str:
    parsed = urlsplit(uri)
    if parsed.username is None:
        return uri
    host = parsed.hostname or ""
    if parsed.port:
        host += f":{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))


class CupsPrinter:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _connection(self):
        cups = _cups()
        try:
            return cups.Connection(host=self.settings.cups_server, port=self.settings.cups_port)
        except RuntimeError as exc:
            raise PrinterUnavailable("cannot connect to the CUPS service") from exc

    def _attributes(self, printer: str) -> dict[str, Any]:
        cups = _cups()
        connection = self._connection()
        printers = connection.getPrinters()
        if printer not in printers:
            raise PrinterUnavailable(f"queue {printer!r} is not configured in CUPS")
        try:
            return connection.getPrinterAttributes(printer)
        except cups.IPPError as exc:
            raise PrinterUnavailable("could not read printer capabilities") from exc

    async def list_printers(self) -> list[PrinterInfo]:
        def read() -> list[PrinterInfo]:
            cups = _cups()
            try:
                connection = self._connection()
                queues = connection.getPrinters()
            except PrinterUnavailable:
                return []
            results: list[PrinterInfo] = []
            for name, summary in sorted(queues.items()):
                try:
                    attributes = connection.getPrinterAttributes(name)
                except cups.IPPError:
                    attributes = summary
                state = int(attributes.get("printer-state", 5))
                reasons = _as_list(attributes.get("printer-state-reasons"))
                results.append(
                    PrinterInfo(
                        name=name,
                        uri=redact_uri(str(attributes.get("device-uri", ""))),
                        available=state != 5 and "offline" not in " ".join(reasons),
                        state=PRINTER_STATES.get(state, f"unknown-{state}"),
                        state_reasons=reasons,
                        media_supported=_as_list(attributes.get("media-supported")),
                        sides_supported=_as_list(attributes.get("sides-supported")),
                        color_modes_supported=_as_list(
                            attributes.get("print-color-mode-supported")
                        ),
                    )
                )
            return results

        return await asyncio.to_thread(read)

    async def submit(
        self,
        pdf: Path,
        printer: str | None,
        title: str,
        page_size: PageSize,
        copies: int,
        sides: Sides,
        color_mode: ColorMode,
    ) -> tuple[int, str]:
        def print_file() -> tuple[int, str]:
            cups = _cups()
            connection = self._connection()
            chosen_printer = printer or self.settings.default_printer or connection.getDefault()
            if not chosen_printer:
                raise PrinterUnavailable("no printer was selected and CUPS has no default queue")
            attributes = self._attributes(chosen_printer)
            supported_sides = _as_list(attributes.get("sides-supported"))
            supported_colors = _as_list(attributes.get("print-color-mode-supported"))
            if supported_sides and sides.value not in supported_sides:
                raise UnsupportedOption(f"printer does not support {sides.value}")
            if (
                color_mode != ColorMode.AUTO
                and supported_colors
                and color_mode.value not in supported_colors
            ):
                raise UnsupportedOption(f"printer does not support {color_mode.value} output")
            options = {
                "media": MEDIA_OPTIONS[page_size],
                "copies": str(copies),
                "sides": sides.value,
            }
            if color_mode != ColorMode.AUTO:
                options["print-color-mode"] = color_mode.value
            try:
                job_id = int(connection.printFile(chosen_printer, str(pdf), title, options))
                return job_id, chosen_printer
            except cups.IPPError as exc:
                raise SubmissionFailed("CUPS rejected the print job") from exc

        return await asyncio.to_thread(print_file)

    async def get_job(self, job_id: int) -> JobInfo:
        def read() -> JobInfo:
            cups = _cups()
            try:
                attributes = self._connection().getJobAttributes(job_id)
            except cups.IPPError as exc:
                raise JobNotFound(f"job {job_id} was not found") from exc
            state = int(attributes.get("job-state", 0))

            def timestamp(name: str) -> datetime | None:
                value = attributes.get(name)
                return datetime.fromtimestamp(int(value), UTC) if value else None

            return JobInfo(
                job_id=job_id,
                state=JOB_STATES.get(state, f"unknown-{state}"),
                state_reasons=_as_list(attributes.get("job-state-reasons")),
                title=attributes.get("job-name"),
                created_at=timestamp("time-at-creation"),
                completed_at=timestamp("time-at-completed"),
            )

        return await asyncio.to_thread(read)
