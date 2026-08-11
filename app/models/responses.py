from typing import Any, Optional

from pydantic import BaseModel


class ScreenshotMetadata(BaseModel):
    url: str
    fileName: str
    format: str
    fullPage: bool
    capturedAt: str
    fileSize: int
    contentType: str
    processingTime: int


class ScreenshotResponse(BaseModel):
    success: bool
    screenshotUrl: str
    # Rendered visible text of the captured page. Optional so a client reading an older
    # deployment (before this field existed) degrades instead of failing.
    pageText: Optional[str] = None
    metadata: ScreenshotMetadata


class ImagePosition(BaseModel):
    x: int
    y: int
    visible: bool


class ExtractedImage(BaseModel):
    src: str
    srcset: Optional[str] = None
    alt: str
    width: int
    height: int
    format: str
    position: ImagePosition
    classification: str
    isLazyLoaded: bool
    anchorHref: Optional[str] = None


class ImageExtractionMetadata(BaseModel):
    processingTime: int
    totalImages: int
    filteredOut: int
    lazyLoadedCount: int
    unprobedDropped: int = 0
    elapsedMs: int


class ImageExtractionResponse(BaseModel):
    success: bool
    url: str
    totalImages: int
    images: list[ExtractedImage]
    metadata: ImageExtractionMetadata


class CrawledImage(ExtractedImage):
    pageUrl: str


class CrawlPageResult(BaseModel):
    url: str
    status: str  # "ok" | "error" | "timeout" | "skipped_budget"
    imagesFound: int = 0
    durationMs: int = 0
    score: float = 0
    screenshotUrl: Optional[str] = None
    error: Optional[str] = None


class CrawlResponse(BaseModel):
    success: bool
    url: str
    partial: bool
    totalImages: int
    images: list[CrawledImage]
    pages: list[CrawlPageResult]
    metadata: dict[str, Any]


class ErrorResponse(BaseModel):
    error: str
    timeout: Optional[bool] = None
    retryable: Optional[bool] = None
    success: Optional[bool] = None
