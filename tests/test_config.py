import pytest
from pydantic import ValidationError

from print_mcp.config import Settings


def test_rejects_short_bearer_token() -> None:
    with pytest.raises(ValidationError):
        Settings(mcp_bearer_token="short")


def test_allowed_origins_are_normalized() -> None:
    settings = Settings(
        mcp_bearer_token="x" * 32,
        mcp_allowed_origins="https://one.example/, https://two.example",
    )
    assert settings.allowed_origins == {
        "https://one.example",
        "https://two.example",
    }
