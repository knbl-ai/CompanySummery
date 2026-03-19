import asyncio
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.middleware.security import validate_url
from app.models.requests import ScreenshotRequest
from app.services.screenshot_service import capture_screenshot
from app.services.storage_service import storage_service

logger = logging.getLogger(__name__)
router = APIRouter()

_MAX_ATTEMPTS = 2
_RETRY_BACKOFF_S = 2.0


@router.post("/screenshot")
async def screenshot(request: Request, body: ScreenshotRequest):
    start = time.time()

    # SSRF validation
    valid, reason = validate_url(body.url)
    if not valid:
        return JSONResponse(status_code=400, content={"error": "Invalid URL", "message": reason})

    last_exc = None
    for attempt in range(_MAX_ATTEMPTS):
        if attempt > 0:
            logger.warning("Retrying screenshot for %s (attempt %d/%d)...", body.url, attempt + 1, _MAX_ATTEMPTS)
            await asyncio.sleep(_RETRY_BACKOFF_S)
        try:
            buffer = await capture_screenshot(
                url=body.url,
                full_page=body.fullPage,
                fmt=body.format,
                quality=body.quality,
                delay=body.delay,
            )
            last_exc = None
            break
        except asyncio.TimeoutError as e:
            last_exc = e
        except Exception as e:
            last_exc = e

    if last_exc is not None:
        if isinstance(last_exc, asyncio.TimeoutError):
            return JSONResponse(
                status_code=504,
                content={"error": "Screenshot capture timed out", "timeout": True, "retryable": True},
            )
        logger.exception("Screenshot error for %s", body.url)
        return JSONResponse(status_code=500, content={"error": str(last_exc), "retryable": False})

    upload_result = await storage_service.upload_screenshot(buffer, fmt=body.format)

    processing_time = int((time.time() - start) * 1000)

    return {
        "success": True,
        "screenshotUrl": upload_result["url"],
        "metadata": {
            "url": body.url,
            "fileName": upload_result["fileName"],
            "format": body.format,
            "fullPage": body.fullPage,
            "capturedAt": datetime.now(timezone.utc).isoformat(),
            "fileSize": upload_result["fileSize"],
            "contentType": upload_result["contentType"],
            "processingTime": processing_time,
        },
    }
