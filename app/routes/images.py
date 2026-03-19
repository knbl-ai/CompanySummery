import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.middleware.security import validate_url
from app.models.requests import ImageExtractionRequest
from app.services.image_extraction_service import extract_images

logger = logging.getLogger(__name__)
router = APIRouter()

_MAX_ATTEMPTS = 2
_RETRY_BACKOFF_S = 2.0


@router.post("/extract-images")
async def extract_images_endpoint(request: Request, body: ImageExtractionRequest):
    # SSRF validation
    valid, reason = validate_url(body.url)
    if not valid:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Invalid URL", "message": reason},
        )

    opts = body.options
    min_width = opts.minWidth if opts else None
    min_height = opts.minHeight if opts else None
    max_images = opts.maxImages if opts else 100

    last_exc = None
    for attempt in range(_MAX_ATTEMPTS):
        if attempt > 0:
            logger.warning("Retrying image extraction for %s (attempt %d/%d)...", body.url, attempt + 1, _MAX_ATTEMPTS)
            await asyncio.sleep(_RETRY_BACKOFF_S)
        try:
            result = await extract_images(
                url=body.url,
                min_width=min_width,
                min_height=min_height,
                max_images=max_images,
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
                content={"success": False, "error": "Image extraction timed out", "timeout": True, "retryable": True},
            )
        logger.exception("Image extraction error for %s", body.url)
        return JSONResponse(status_code=500, content={"success": False, "error": str(last_exc), "retryable": False})

    return {
        "success": True,
        "url": body.url,
        "totalImages": result["metadata"]["totalImages"],
        "images": result["images"],
        "metadata": result["metadata"],
    }
