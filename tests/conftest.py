import pytest

from print_mcp.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        mcp_bearer_token="a" * 32,
        cups_server="localhost",
        max_images=3,
        max_image_bytes=1024 * 1024,
        max_total_image_bytes=2 * 1024 * 1024,
    )
