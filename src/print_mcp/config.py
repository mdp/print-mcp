from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mcp_bearer_token: str = Field(min_length=32)
    mcp_allowed_origins: str = ""
    mcp_allowed_hosts: str = ""
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)

    cups_server: str = "cups"
    cups_port: int = Field(default=631, ge=1, le=65535)
    default_printer: str = ""

    default_page_size: str = "letter"
    default_margin_mm: float = Field(default=17.8, ge=5, le=30)
    max_markdown_bytes: int = Field(default=524_288, ge=1024)
    max_images: int = Field(default=20, ge=0, le=100)
    max_image_bytes: int = Field(default=10_485_760, ge=1024)
    max_total_image_bytes: int = Field(default=26_214_400, ge=1024)
    image_fetch_timeout_seconds: float = Field(default=10, ge=1, le=60)
    max_pdf_bytes: int = Field(default=52_428_800, ge=1024)
    max_pages: int = Field(default=100, ge=1, le=1000)
    render_timeout_seconds: float = Field(default=30, ge=1, le=300)
    max_concurrent_renders: int = Field(default=2, ge=1, le=8)

    @field_validator("default_page_size")
    @classmethod
    def valid_page_size(cls, value: str) -> str:
        value = value.lower()
        if value not in {"letter", "legal", "a4"}:
            raise ValueError("must be letter, legal, or a4")
        return value

    @property
    def allowed_origins(self) -> frozenset[str]:
        return frozenset(
            item.strip().rstrip("/") for item in self.mcp_allowed_origins.split(",") if item.strip()
        )

    @property
    def allowed_hosts(self) -> list[str]:
        defaults = ["127.0.0.1:*", "localhost:*", "[::1]:*", "mcp:*"]
        configured = [item.strip() for item in self.mcp_allowed_hosts.split(",") if item.strip()]
        return defaults + configured


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
