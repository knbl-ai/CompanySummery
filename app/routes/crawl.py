import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.limits import limiter
from app.middleware.security import validate_url
from app.models.requests import CrawlOptions, CrawlRequest
from app.services.crawl_service import crawl_images

logger = logging.getLogger(__name__)
router = APIRouter()


# Tighter than the global limit: one crawl costs ~8 page renders and can hold a
# browser slot for minutes. No route-level retry either — the crawl itself
# degrades to partial results instead of failing on slow pages.
@router.post("/crawl-images")
@limiter.limit("20/15minutes")
async def crawl_images_endpoint(request: Request, body: CrawlRequest):
    valid, reason = validate_url(body.url)
    if not valid:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Invalid URL", "message": reason},
        )

    opts = body.options or CrawlOptions()
    try:
        result = await crawl_images(
            body.url,
            max_pages=opts.maxPages,
            max_images=opts.maxImages,
            min_width=opts.minWidth,
            min_height=opts.minHeight,
            include_backgrounds=opts.includeBackgrounds,
            priority_keywords=opts.priorityKeywords,
            include_screenshots=opts.includeScreenshots,
            use_sitemap=opts.useSitemap,
            time_budget_ms=opts.timeBudgetMs,
        )
    except Exception as e:
        logger.exception("Crawl failed for %s", body.url)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)[:300], "retryable": True},
        )

    return {
        "success": True,
        "url": body.url,
        "partial": result["partial"],
        "totalImages": len(result["images"]),
        "images": result["images"],
        "pages": result["pages"],
        "metadata": result["metadata"],
    }
