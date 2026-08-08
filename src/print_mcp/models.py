from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class PageSize(StrEnum):
    LETTER = "letter"
    LEGAL = "legal"
    A4 = "a4"


class Orientation(StrEnum):
    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"


class Sides(StrEnum):
    ONE_SIDED = "one-sided"
    LONG_EDGE = "two-sided-long-edge"
    SHORT_EDGE = "two-sided-short-edge"


class ColorMode(StrEnum):
    AUTO = "auto"
    COLOR = "color"
    MONOCHROME = "monochrome"


class PageMargins(BaseModel):
    top: float = Field(default=17.8, ge=5, le=30, description="Top margin in millimetres")
    right: float = Field(default=17.8, ge=5, le=30, description="Right margin in millimetres")
    bottom: float = Field(default=17.8, ge=5, le=30, description="Bottom margin in millimetres")
    left: float = Field(default=17.8, ge=5, le=30, description="Left margin in millimetres")


class PrintResult(BaseModel):
    job_id: int
    printer: str
    title: str
    page_count: int
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    state: str


class PrinterInfo(BaseModel):
    name: str
    uri: str
    available: bool
    state: str
    state_reasons: list[str] = Field(default_factory=list)
    media_supported: list[str] = Field(default_factory=list)
    sides_supported: list[str] = Field(default_factory=list)
    color_modes_supported: list[str] = Field(default_factory=list)


class JobInfo(BaseModel):
    job_id: int
    state: str
    state_reasons: list[str] = Field(default_factory=list)
    title: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None
