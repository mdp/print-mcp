import base64
import socket

import pytest

from print_mcp.errors import ImageFetchFailed, InvalidInput
from print_mcp.models import Orientation, PageMargins, PageSize
from print_mcp.render import PublicOnlyResolver, markdown_to_html, render_markdown_pdf


async def test_markdown_escapes_raw_html(settings) -> None:
    html = await markdown_to_html("# Hello\n<script>alert(1)</script>", settings)
    assert "<h1>Hello</h1>" in html
    assert "<script>" not in html


async def test_data_image_is_embedded(settings) -> None:
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    source = base64.b64encode(png).decode()
    html = await markdown_to_html(f"![pixel](data:image/png;base64,{source})", settings)
    assert "data:image/png;base64," in html


async def test_markdown_size_limit(settings) -> None:
    settings.max_markdown_bytes = 10
    with pytest.raises(InvalidInput):
        await markdown_to_html("x" * 11, settings)


async def test_public_resolver_blocks_private_addresses(monkeypatch) -> None:
    async def fake_getaddrinfo(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]

    loop = __import__("asyncio").get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(OSError, match="non-public"):
        await PublicOnlyResolver().resolve("example.test", 80)


async def test_rejects_non_image_data(settings) -> None:
    payload = base64.b64encode(b"not an image").decode()
    with pytest.raises(ImageFetchFailed):
        await markdown_to_html(f"![bad](data:image/png;base64,{payload})", settings)


async def test_renders_letter_pdf(tmp_path, settings) -> None:
    destination = tmp_path / "document.pdf"
    result = await render_markdown_pdf(
        "# Print test\n\nA paragraph with **bold text**.",
        destination,
        settings,
        PageSize.LETTER,
        Orientation.PORTRAIT,
        PageMargins(),
    )
    assert result.page_count == 1
    assert destination.read_bytes().startswith(b"%PDF")
