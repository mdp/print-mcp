from __future__ import annotations

import asyncio
import base64
import ipaddress
import multiprocessing
import socket
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote_to_bytes, urlparse

import aiohttp
import bleach
from aiohttp.abc import AbstractResolver
from bs4 import BeautifulSoup
from defusedxml import ElementTree
from markdown_it import MarkdownIt
from mdit_py_plugins.tasklists import tasklists_plugin
from PIL import Image
from pygments.formatters import HtmlFormatter
from weasyprint import CSS, HTML

from .config import Settings
from .errors import ImageFetchFailed, InvalidInput, RenderFailed
from .models import Orientation, PageMargins, PageSize

ALLOWED_TAGS = {
    "a",
    "blockquote",
    "br",
    "code",
    "del",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "img",
    "input",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}
ALLOWED_ATTRIBUTES = {
    "a": ["href", "title"],
    "img": ["src", "alt", "title"],
    "input": ["type", "checked", "disabled"],
    "code": ["class"],
}
RASTER_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
IMAGE_TYPES = RASTER_TYPES | {"image/svg+xml"}


class PublicOnlyResolver(AbstractResolver):
    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET) -> list[dict]:
        loop = asyncio.get_running_loop()
        try:
            records = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM, family=family)
        except socket.gaierror as exc:
            raise OSError(f"could not resolve image host {host!r}") from exc
        results: list[dict] = []
        seen: set[str] = set()
        for record_family, _, proto, _, sockaddr in records:
            address = sockaddr[0]
            ip = ipaddress.ip_address(address)
            if not ip.is_global:
                raise OSError(f"image host {host!r} resolves to a non-public address")
            if address in seen:
                continue
            seen.add(address)
            results.append(
                {
                    "hostname": host,
                    "host": address,
                    "port": port,
                    "family": record_family,
                    "proto": proto,
                    "flags": socket.AI_NUMERICHOST,
                }
            )
        return results

    async def close(self) -> None:
        return None


@dataclass(frozen=True)
class RenderedDocument:
    path: Path
    page_count: int


def _markdown() -> MarkdownIt:
    return (
        MarkdownIt("commonmark", {"html": False, "linkify": True, "typographer": True})
        .enable("table")
        .enable("strikethrough")
        .use(tasklists_plugin, enabled=True)
    )


def _stylesheet(page_size: PageSize, orientation: Orientation, margins: PageMargins) -> str:
    size = {PageSize.LETTER: "Letter", PageSize.LEGAL: "Legal", PageSize.A4: "A4"}[page_size]
    return f"""
    @page {{
      size: {size} {orientation.value};
      margin: {margins.top}mm {margins.right}mm {margins.bottom}mm {margins.left}mm;
      @bottom-center {{
        content: "Page " counter(page) " of " counter(pages);
        font: 8pt sans-serif; color: #666;
      }}
    }}
    html {{ font-size: 10.5pt; }}
    body {{ font-family: "Noto Serif", serif; line-height: 1.48; color: #171717; }}
    h1, h2, h3, h4, h5, h6 {{
      font-family: "Noto Sans", sans-serif; line-height: 1.2; page-break-after: avoid;
    }}
    h1 {{ font-size: 23pt; border-bottom: 1px solid #bbb; padding-bottom: 5pt; }}
    h2 {{ font-size: 17pt; margin-top: 20pt; }} h3 {{ font-size: 13pt; }}
    p, li {{ orphans: 3; widows: 3; }} a {{ color: #1557a0; overflow-wrap: anywhere; }}
    blockquote {{ margin-left: 0; padding: 2pt 12pt; border-left: 3pt solid #aaa; color: #444; }}
    pre, code {{ font-family: "Noto Sans Mono", monospace; }}
    code {{ background: #f2f2f2; padding: 1pt 2pt; border-radius: 2pt; }}
    pre {{
      background: #f5f5f5; border: 1px solid #ddd; padding: 9pt;
      white-space: pre-wrap; overflow-wrap: anywhere; page-break-inside: avoid;
    }}
    pre code {{ padding: 0; background: transparent; }}
    table {{
      border-collapse: collapse; width: 100%;
      font-family: "Noto Sans", sans-serif; font-size: 9pt;
    }}
    thead {{ display: table-header-group; }} tr {{ page-break-inside: avoid; }}
    th, td {{ border: 1px solid #bbb; padding: 5pt; vertical-align: top; overflow-wrap: anywhere; }}
    th {{ background: #ededed; text-align: left; }}
    img {{
      display: block; max-width: 100%; max-height: 225mm;
      margin: 8pt auto; object-fit: contain;
    }}
    hr {{ border: 0; border-top: 1px solid #aaa; margin: 18pt 0; }}
    ul.task-list {{ list-style: none; padding-left: 1.2em; }}
    {HtmlFormatter().get_style_defs(".highlight")}
    """


def _sanitize_svg(data: bytes) -> None:
    try:
        root = ElementTree.fromstring(data)
    except Exception as exc:
        raise ImageFetchFailed("invalid SVG image") from exc
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1].lower() == "script":
            raise ImageFetchFailed("SVG scripts are not allowed")
        for key, value in element.attrib.items():
            if key.rsplit("}", 1)[-1].lower() in {"href", "src"}:
                parsed = urlparse(value)
                if parsed.scheme and parsed.scheme != "data":
                    raise ImageFetchFailed("external references inside SVG images are not allowed")


def _validate_image(data: bytes, content_type: str) -> str:
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime == "image/svg+xml" or data.lstrip().startswith(b"<svg"):
        _sanitize_svg(data)
        return "image/svg+xml"
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
            detected = Image.MIME.get(image.format or "", "")
    except Exception as exc:
        raise ImageFetchFailed("image payload is not a supported image") from exc
    if detected not in RASTER_TYPES:
        raise ImageFetchFailed(f"unsupported image type {detected or mime or 'unknown'}")
    return detected


def _read_data_image(uri: str, maximum: int) -> tuple[bytes, str]:
    try:
        header, payload = uri.split(",", 1)
        media = header[5:].split(";", 1)[0].lower()
        data = (
            base64.b64decode(payload, validate=True)
            if ";base64" in header
            else unquote_to_bytes(payload)
        )
    except (ValueError, TypeError) as exc:
        raise ImageFetchFailed("invalid data image URI") from exc
    if len(data) > maximum:
        raise ImageFetchFailed("data image exceeds the per-image size limit")
    return data, _validate_image(data, media)


async def _download_image(
    session: aiohttp.ClientSession, uri: str, maximum: int
) -> tuple[bytes, str]:
    parsed = urlparse(uri)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ImageFetchFailed("images must use HTTP, HTTPS, or data URIs")
    try:
        async with session.get(uri, allow_redirects=True, max_redirects=4) as response:
            response.raise_for_status()
            if int(response.headers.get("Content-Length", "0")) > maximum:
                raise ImageFetchFailed("image exceeds the per-image size limit")
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.content.iter_chunked(65_536):
                size += len(chunk)
                if size > maximum:
                    raise ImageFetchFailed("image exceeds the per-image size limit")
                chunks.append(chunk)
            data = b"".join(chunks)
            return data, _validate_image(data, response.headers.get("Content-Type", ""))
    except ImageFetchFailed:
        raise
    except Exception as exc:
        raise ImageFetchFailed(f"could not fetch image from {parsed.hostname}") from exc


async def markdown_to_html(markdown: str, settings: Settings) -> str:
    if len(markdown.encode("utf-8")) > settings.max_markdown_bytes:
        raise InvalidInput("Markdown exceeds the configured size limit")
    rendered = _markdown().render(markdown)
    cleaned = bleach.clean(
        rendered,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols={"http", "https", "data", "mailto"},
        strip=True,
    )
    soup = BeautifulSoup(cleaned, "html.parser")
    images = soup.find_all("img")
    if len(images) > settings.max_images:
        raise ImageFetchFailed("document contains too many images")

    timeout = aiohttp.ClientTimeout(total=settings.image_fetch_timeout_seconds)
    connector = aiohttp.TCPConnector(resolver=PublicOnlyResolver(), use_dns_cache=True)
    total = 0
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        for image in images:
            source = str(image.get("src", ""))
            if source.startswith("data:"):
                data, mime = _read_data_image(source, settings.max_image_bytes)
            else:
                data, mime = await _download_image(session, source, settings.max_image_bytes)
            total += len(data)
            if total > settings.max_total_image_bytes:
                raise ImageFetchFailed("images exceed the aggregate size limit")
            image["src"] = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
    return str(soup)


def _deny_external_fetch(url: str, *args, **kwargs) -> dict:
    if not url.startswith("data:"):
        raise ValueError("external resource access is disabled during rendering")
    from weasyprint import default_url_fetcher

    return default_url_fetcher(url, *args, **kwargs)


def _render_worker(html: str, css: str, destination: str, result_queue) -> None:
    try:
        document = HTML(string=html, url_fetcher=_deny_external_fetch).render(
            stylesheets=[CSS(string=css)]
        )
        document.write_pdf(destination)
        result_queue.put((len(document.pages), None))
    except Exception as exc:
        result_queue.put((0, str(exc)))


def _render_with_deadline(html: str, css: str, destination: Path, timeout: float) -> int:
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue(maxsize=1)
    process = context.Process(
        target=_render_worker, args=(html, css, str(destination), result_queue)
    )
    process.start()
    process.join(timeout)
    if process.is_alive():
        process.terminate()
        process.join(5)
        raise RenderFailed("rendering exceeded the configured time limit")
    if result_queue.empty():
        raise RenderFailed("renderer exited without producing a document")
    pages, error = result_queue.get_nowait()
    if error:
        raise RenderFailed(error)
    return pages


async def render_markdown_pdf(
    markdown: str,
    destination: Path,
    settings: Settings,
    page_size: PageSize,
    orientation: Orientation,
    margins: PageMargins,
) -> RenderedDocument:
    html = await markdown_to_html(markdown, settings)
    css = _stylesheet(page_size, orientation, margins)
    pages = await asyncio.to_thread(
        _render_with_deadline, html, css, destination, settings.render_timeout_seconds
    )
    if pages > settings.max_pages:
        destination.unlink(missing_ok=True)
        raise RenderFailed("rendered document exceeds the page limit")
    if not destination.exists() or destination.stat().st_size > settings.max_pdf_bytes:
        destination.unlink(missing_ok=True)
        raise RenderFailed("rendered PDF exceeds the size limit")
    return RenderedDocument(path=destination, page_count=pages)
