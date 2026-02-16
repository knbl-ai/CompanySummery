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


@router.post("/screenshot")
async def screenshot(request: Request, body: ScreenshotRequest):
    start = time.time()

    # SSRF validation
    valid, reason = validate_url(body.url)
    if not valid:
        return JSONResponse(status_code=400, content={"error": "Invalid URL", "message": reason})

    try:
        buffer = await capture_screenshot(
            url=body.url,
            full_page=body.fullPage,
            fmt=body.format,
            quality=body.quality,
            delay=body.delay,
        )

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

    except asyncio.TimeoutError:
        return JSONResponse(
            status_code=504,
            content={
                "error": "Screenshot capture timed out",
                "timeout": True,
                "retryable": True,
            },
        )
    except Exception as e:
        logger.exception("Screenshot error for %s", body.url)
        return JSONResponse(
            status_code=500,
            content={
                "error": str(e),
                "retryable": False,
            },
        )
