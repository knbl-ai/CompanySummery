from typing import Optional

from pydantic import BaseModel, Field, field_validator


class ScreenshotRequest(BaseModel):
    url: str
    fullPage: bool = True
    format: str = "png"
    quality: int = 90
    delay: int = 0

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        if v not in ("png", "jpeg", "webp"):
            raise ValueError("Invalid format. Must be png, jpeg, or webp")
        return v

    @field_validator("quality")
    @classmethod
    def validate_quality(cls, v: int) -> int:
        if v < 1 or v > 100:
            raise ValueError("Quality must be between 1 and 100")
        return v

    @field_validator("delay")
    @classmethod
    def validate_delay(cls, v: int) -> int:
        if v < 0 or v > 30000:
            raise ValueError("Delay must be between 0 and 30000 milliseconds")
        return v


class ImageExtractionOptions(BaseModel):
    minWidth: int = Field(default=100, ge=0)
    minHeight: int = Field(default=100, ge=0)
    maxImages: int = Field(default=100, ge=1, le=500)
    # None → service default (settings.image_include_backgrounds). Explicitly true
    # enables the CSS background-image channel — essential for image-led sites
    # (hotels, portfolios) that paint photography via background:url(...).
    includeBackgrounds: Optional[bool] = None


class ImageExtractionRequest(BaseModel):
    url: str
    options: Optional[ImageExtractionOptions] = None


class CrawlOptions(BaseModel):
    maxPages: int = Field(default=8, ge=1, le=20)
    maxImages: int = Field(default=200, ge=1, le=1000)
    minWidth: int = Field(default=100, ge=0)
    minHeight: int = Field(default=100, ge=0)
    includeBackgrounds: bool = True
    # Extends (not replaces) the built-in page-priority keywords, at top weight.
    priorityKeywords: Optional[list[str]] = None
    includeScreenshots: bool = False
    useSitemap: bool = True
    timeBudgetMs: int = Field(default=240000, ge=30000, le=280000)


class CrawlRequest(BaseModel):
    url: str
    options: Optional[CrawlOptions] = None
