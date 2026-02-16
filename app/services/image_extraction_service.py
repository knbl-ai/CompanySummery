import asyncio
import logging
import time

from app.config import settings
from app.services.browser_pool import browser_pool

logger = logging.getLogger(__name__)

# JavaScript to extract image data from the page — ported directly from the Node.js version
EXTRACT_IMAGES_JS = """(includeBackgrounds) => {
    const images = [];
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;

    const imgElements = Array.from(document.querySelectorAll('img'));

    imgElements.forEach((img, index) => {
        const rect = img.getBoundingClientRect();

        let inHeader = false;
        let parentEl = img.parentElement;
        let depth = 0;
        while (parentEl && depth < 5) {
            const tagName = parentEl.tagName.toLowerCase();
            if (tagName === 'header' || tagName === 'nav') {
                inHeader = true;
                break;
            }
            parentEl = parentEl.parentElement;
            depth++;
        }

        const src = img.src || '';
        const alt = img.alt || '';
        const className = img.className || '';
        const containsLogo =
            src.toLowerCase().includes('logo') ||
            alt.toLowerCase().includes('logo') ||
            className.toLowerCase().includes('logo');

        const productKeywords = ['product', 'iphone', 'macbook', 'ipad', 'watch', 'airpods', 'laptop', 'phone', 'tablet'];
        const containsProductKeywords = productKeywords.some(keyword =>
            src.toLowerCase().includes(keyword) ||
            alt.toLowerCase().includes(keyword) ||
            className.toLowerCase().includes(keyword)
        );

        const isLazyLoaded =
            img.hasAttribute('data-src') ||
            img.hasAttribute('loading') ||
            img.hasAttribute('data-lazy');

        let format = 'unknown';
        if (src) {
            const ext = src.split('.').pop().split('?')[0].toLowerCase();
            if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp'].includes(ext)) {
                format = ext === 'jpg' ? 'jpeg' : ext;
            }
        }

        images.push({
            src: src,
            srcset: img.srcset || null,
            alt: alt,
            width: img.naturalWidth || 0,
            height: img.naturalHeight || 0,
            format: format,
            position: {
                x: Math.round(rect.left),
                y: Math.round(rect.top),
                visible: rect.top < viewportHeight && rect.bottom > 0 && rect.left < viewportWidth && rect.right > 0
            },
            containsLogo: containsLogo,
            containsProductKeywords: containsProductKeywords,
            inHeader: inHeader,
            isLazyLoaded: isLazyLoaded,
            className: className,
            parentTag: img.parentElement ? img.parentElement.tagName.toLowerCase() : null
        });
    });

    if (includeBackgrounds) {
        const allElements = Array.from(document.querySelectorAll('*'));

        allElements.forEach(el => {
            const style = window.getComputedStyle(el);
            const bgImage = style.backgroundImage;

            if (bgImage && bgImage !== 'none' && bgImage.includes('url(')) {
                const urlMatch = bgImage.match(/url\\(['"]?([^'"]+)['"]?\\)/);
                if (urlMatch && urlMatch[1]) {
                    const url = urlMatch[1];
                    if (url.startsWith('data:')) return;

                    const rect = el.getBoundingClientRect();

                    images.push({
                        src: url,
                        srcset: null,
                        alt: '',
                        width: Math.round(rect.width),
                        height: Math.round(rect.height),
                        format: 'background',
                        position: {
                            x: Math.round(rect.left),
                            y: Math.round(rect.top),
                            visible: rect.top < viewportHeight && rect.bottom > 0
                        },
                        containsLogo: false,
                        containsProductKeywords: false,
                        inHeader: false,
                        isLazyLoaded: false,
                        className: el.className || '',
                        parentTag: 'background'
                    });
                }
            }
        });
    }

    const lazyLoadedCount = images.filter(img => img.isLazyLoaded).length;

    return {
        allImages: images,
        pageContext: {
            viewportWidth: viewportWidth,
            viewportHeight: viewportHeight,
            scrollHeight: document.body.scrollHeight
        },
        lazyLoadedCount: lazyLoadedCount
    };
}"""


def _filter_images(images: list[dict], min_width: int, min_height: int) -> list[dict]:
    result = []
    for img in images:
        if img["width"] < min_width or img["height"] < min_height:
            continue
        if img["width"] == 1 and img["height"] == 1:
            continue
        src = img.get("src", "")
        if not src or src.startswith("data:"):
            continue
        result.append(img)
    return result


def _classify_images(images: list[dict], page_context: dict) -> list[dict]:
    vw = page_context["viewportWidth"]
    vh = page_context["viewportHeight"]

    result = []
    for img in images:
        classification = "content"

        if (
            img["position"]["y"] < vh * 0.2
            and img["width"] > vw * 0.5
            and img["height"] > 400
        ):
            classification = "hero"
        elif img.get("containsLogo") and img.get("inHeader") and img["width"] < 300:
            classification = "logo"
        elif (
            img["width"] >= 300
            and img["height"] >= 200
            and img.get("containsProductKeywords")
        ):
            classification = "product"
        elif img["width"] < 100 and img["height"] < 100:
            classification = "icon"
        elif 100 <= img["width"] < 400 and 100 <= img["height"] < 400:
            classification = "thumbnail"

        result.append(
            {
                "src": img["src"],
                "srcset": img.get("srcset"),
                "alt": img.get("alt", ""),
                "width": img["width"],
                "height": img["height"],
                "format": img.get("format", "unknown"),
                "position": img["position"],
                "classification": classification,
                "isLazyLoaded": img.get("isLazyLoaded", False),
            }
        )
    return result


async def extract_images(
    url: str,
    min_width: int | None = None,
    min_height: int | None = None,
    max_images: int = 100,
    include_backgrounds: bool = False,
) -> dict:
    if min_width is None:
        min_width = settings.image_min_width
    if min_height is None:
        min_height = settings.image_min_height

    overall_timeout = settings.image_extraction_timeout / 1000
    start = time.time()

    async def _do_extract() -> dict:
        context = await browser_pool.acquire_context()
        try:
            page = await context.new_page()

            nav_timeout = settings.screenshot_page_navigation_timeout
            logger.info("Navigating to %s for image extraction...", url)

            await page.goto(url, wait_until="commit", timeout=nav_timeout)
            logger.info("Navigation committed, waiting for load state...")

            try:
                await page.wait_for_load_state("load", timeout=30000)
                logger.info("Load state reached")
            except Exception:
                logger.info("Load state timeout (30s), continuing...")

            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                logger.info("Network idle timeout, continuing...")

            # Wait for page body to have meaningful content (SPA support)
            await page.evaluate("""async () => {
                const maxWait = 10000;
                const start = Date.now();
                while (Date.now() - start < maxWait) {
                    if (document.body && document.body.innerHTML.length > 500) return;
                    await new Promise(r => setTimeout(r, 300));
                }
            }""")

            # Auto-scroll with 80% viewport height, 200ms delay
            await page.evaluate("""async () => {
                await new Promise((resolve) => {
                    const viewportHeight = window.innerHeight;
                    const distance = Math.floor(viewportHeight * 0.8);
                    const maxHeight = 15000;
                    const scrollTimeout = 40000;
                    const startTime = Date.now();
                    let totalHeight = 0;

                    const timer = setInterval(() => {
                        const scrollHeight = document.body.scrollHeight;
                        window.scrollBy(0, distance);
                        totalHeight += distance;

                        if (totalHeight >= scrollHeight - viewportHeight || totalHeight >= maxHeight || Date.now() - startTime >= scrollTimeout) {
                            clearInterval(timer);
                            window.scrollTo(0, 0);
                            resolve();
                        }
                    }, 200);
                });
            }""")

            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                logger.info("Network idle timeout after scroll, continuing...")

            # Wait for images to load
            await page.evaluate("""async () => {
                const images = Array.from(document.querySelectorAll('img'));
                await Promise.all(images.map(img => {
                    if (img.complete) return;
                    return new Promise(resolve => {
                        img.addEventListener('load', resolve);
                        img.addEventListener('error', resolve);
                        setTimeout(resolve, 3000);
                    });
                }));
            }""")

            # Post-load delay
            post_load = settings.screenshot_post_load_delay
            if post_load > 0:
                safe_delay = min(post_load, 10000)
                logger.info("Waiting %dms for dynamic content...", safe_delay)
                await asyncio.sleep(safe_delay / 1000)

            # Extract image data using the in-browser JS
            logger.info("Extracting image data...")
            image_data = await page.evaluate(EXTRACT_IMAGES_JS, include_backgrounds)

            all_images = image_data["allImages"]
            page_context = image_data["pageContext"]
            lazy_loaded_count = image_data["lazyLoadedCount"]

            logger.info("Extracted %d total images", len(all_images))

            filtered = _filter_images(all_images, min_width, min_height)
            logger.info("After filtering: %d images", len(filtered))

            limited = filtered[:max_images]
            classified = _classify_images(limited, page_context)

            return {
                "images": classified,
                "filtered_count": len(all_images) - len(filtered),
                "lazy_loaded_count": lazy_loaded_count,
            }
        finally:
            await browser_pool.release_context(context)

    try:
        result = await asyncio.wait_for(_do_extract(), timeout=overall_timeout)
    except asyncio.TimeoutError:
        logger.error("Image extraction timed out after %ds", overall_timeout)
        raise

    elapsed = int((time.time() - start) * 1000)
    processing_time = elapsed

    return {
        "images": result["images"],
        "metadata": {
            "processingTime": processing_time,
            "totalImages": len(result["images"]),
            "filteredOut": result["filtered_count"],
            "lazyLoadedCount": result["lazy_loaded_count"],
            "elapsedMs": elapsed,
        },
    }
