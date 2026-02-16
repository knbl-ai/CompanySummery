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


class ImageExtractionMetadata(BaseModel):
    processingTime: int
    totalImages: int
    filteredOut: int
    lazyLoadedCount: int
    elapsedMs: int


class ImageExtractionResponse(BaseModel):
    success: bool
    url: str
    totalImages: int
    images: list[ExtractedImage]
    metadata: ImageExtractionMetadata


class ErrorResponse(BaseModel):
    error: str
    timeout: Optional[bool] = None
    retryable: Optional[bool] = None
    success: Optional[bool] = None
