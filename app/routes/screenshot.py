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
    capture = None
    for attempt in range(_MAX_ATTEMPTS):
        if attempt > 0:
            logger.warning("Retrying screenshot for %s (attempt %d/%d)...", body.url, attempt + 1, _MAX_ATTEMPTS)
            await asyncio.sleep(_RETRY_BACKOFF_S)
        try:
            capture = await capture_screenshot(
                url=body.url,
                full_page=body.fullPage,
                fmt=body.format,
                quality=body.quality,
                delay=body.delay,
            )
            last_exc = None
            if not capture.blank:
                break
            # An empty frame raises nothing — the JPEG is valid, it just has no page in
            # it — so it never reached the one retry this loop already affords. A fresh
            # page load is a different attempt from a second frame of the same one, which
            # is what the capture itself already tried. Worth spending.
            logger.warning("Capture for %s came back blank — retrying with a fresh page load", body.url)
        except asyncio.TimeoutError as e:
            last_exc = e
        except Exception as e:
            last_exc = e

    # Only an attempt that produced nothing at all is an error. A blank capture still
    # carries the page text, which for a bot-protected site is the caller's only
    # first-party evidence — it goes back flagged, not withheld.
    if capture is None and last_exc is not None:
        if isinstance(last_exc, asyncio.TimeoutError):
            return JSONResponse(
                status_code=504,
                content={"error": "Screenshot capture timed out", "timeout": True, "retryable": True},
            )
        logger.exception("Screenshot error for %s", body.url)
        return JSONResponse(status_code=500, content={"error": str(last_exc), "retryable": False})

    upload_result = await storage_service.upload_screenshot(capture.image, fmt=body.format)

    if capture.blank:
        logger.error(
            "Returning a BLANK capture for %s — the image holds no page. Callers must not "
            "read branding from it", body.url,
        )

    processing_time = int((time.time() - start) * 1000)

    return {
        "success": True,
        "screenshotUrl": upload_result["url"],
        # The image came back empty — a valid file with no page in it. Says nothing about
        # the page itself: `pageText` below is from the same load and is usually intact.
        # A caller that reads brand colours from a screenshot must check this first; a
        # vision model handed an empty frame invents a brand rather than reporting one.
        "blank": capture.blank,
        # The rendered text of the same page load. For a bot-protected site this is the
        # caller's only first-party evidence — without it they are left with web search.
        "pageText": capture.text or None,
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
