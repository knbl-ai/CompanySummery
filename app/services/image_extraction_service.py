import asyncio
import logging
import time

from app.config import settings
from app.services.browser_pool import browser_pool
from app.services.page_prep import (
    AUTO_SCROLL_JS,
    WAIT_FOR_IMAGES_JS,
    dismiss_consent,
    neutralize_animations,
)

logger = logging.getLogger(__name__)

# JavaScript to extract image data from the page.
#
# Three source channels, deduped by URL then dimension-probed:
#   1. <img> elements — the URL returned is the LARGEST srcset candidate
#      (fallback: currentSrc, then src). Browsers pick a viewport-sized srcset
#      candidate and naturalWidth/Height describe THAT pick, while img.src can
#      be a tiny fallback (WP galleries ship src="…-36x36.jpg" with the real
#      sizes in srcset) — reporting src with currentSrc's dimensions hands
#      callers a thumbnail URL labeled with full-size dimensions.
#   2. Attribute-declared sources (data-img-url / data-bg / …) — JS sliders
#      (e.g. the Enfold/avia slideshow) keep their slides in data attributes
#      and paint them as lazy CSS backgrounds, so the page's best photos often
#      have no <img> element at all.
#   3. Computed background-image styles (behind includeBackgrounds).
#
# Candidates whose true size is unknown (channels 2/3, srcset upgrades) are
# probed in-browser with Image() so width/height are always real pixels.
# Every entry carries anchorHref (enclosing <a>) so callers can tell content
# images from navigation cards (e.g. "related projects" carousels).
EXTRACT_IMAGES_JS = """async (includeBackgrounds) => {
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;

    const toAbs = (u) => {
        try { return new URL(u, document.baseURI).href; } catch (e) { return null; }
    };

    const formatOf = (src) => {
        if (!src) return 'unknown';
        const ext = src.split('.').pop().split('?')[0].toLowerCase();
        if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp'].includes(ext)) {
            return ext === 'jpg' ? 'jpeg' : ext;
        }
        return 'unknown';
    };

    // Largest w-descriptor candidate of a srcset, or null.
    const largestSrcsetCandidate = (srcset) => {
        if (!srcset) return null;
        let best = null;
        for (const part of srcset.split(',')) {
            const tokens = part.trim().split(/\\s+/);
            if (!tokens[0]) continue;
            const w = tokens[1] && /^\\d+w$/.test(tokens[1]) ? parseInt(tokens[1]) : 0;
            if (!best || w > best.w) best = { url: tokens[0], w: w };
        }
        return best && best.url ? best : null;
    };

    const anchorHrefOf = (el) => {
        const a = el.closest ? el.closest('a[href]') : null;
        return a ? a.href : null;
    };

    const positionOf = (rect) => ({
        x: Math.round(rect.left),
        y: Math.round(rect.top),
        visible: rect.top < viewportHeight && rect.bottom > 0 && rect.left < viewportWidth && rect.right > 0
    });

    const productKeywords = ['product', 'iphone', 'macbook', 'ipad', 'watch', 'airpods', 'laptop', 'phone', 'tablet'];
    const matchesAny = (haystacks, needles) =>
        needles.some(n => haystacks.some(h => h.includes(n)));

    const candidates = [];

    // --- channel 1: <img> elements -------------------------------------------
    for (const img of Array.from(document.querySelectorAll('img'))) {
        const rect = img.getBoundingClientRect();

        let inHeader = false;
        let parentEl = img.parentElement;
        let depth = 0;
        while (parentEl && depth < 5) {
            const tagName = parentEl.tagName.toLowerCase();
            if (tagName === 'header' || tagName === 'nav') { inHeader = true; break; }
            parentEl = parentEl.parentElement;
            depth++;
        }

        const alt = img.alt || '';
        const className = String(img.className || '');
        let src = img.currentSrc || img.src || '';
        let width = img.naturalWidth || 0;
        let height = img.naturalHeight || 0;
        let needsProbe = false;

        // Unloaded lazy image: the real URL sits in a data attribute.
        if (!src || src.startsWith('data:')) {
            const lazy = img.getAttribute('data-src') || img.getAttribute('data-lazy-src') || img.getAttribute('data-lazy');
            const lazyAbs = lazy && toAbs(lazy);
            if (lazyAbs && !lazyAbs.startsWith('data:')) {
                src = lazyAbs; width = 0; height = 0; needsProbe = true;
            }
        }

        // Upgrade to the largest declared srcset candidate when it beats what
        // the browser loaded for this viewport. Candidates come from the img's
        // own srcset AND any <picture><source srcset> siblings — art-directed
        // pages often keep the real image only in <source>.
        const srcsets = [];
        if (img.srcset) srcsets.push(img.srcset);
        const pic = img.closest ? img.closest('picture') : null;
        if (pic) {
            for (const s of Array.from(pic.querySelectorAll('source[srcset]'))) {
                if (s.srcset) srcsets.push(s.srcset);
            }
        }
        let best = null;
        for (const ss of srcsets) {
            const cand = largestSrcsetCandidate(ss);
            if (cand && (!best || cand.w > best.w)) best = cand;
        }
        if (best) {
            const bestAbs = toAbs(best.url);
            if (bestAbs && bestAbs !== src && best.w >= width) {
                src = bestAbs;
                if (best.w > 0 && width > 0 && height > 0) {
                    // Same image at a different resolution: the w-descriptor is the
                    // true width; scale height by the loaded aspect ratio — no probe.
                    height = Math.round(best.w * height / width);
                    width = best.w;
                    needsProbe = false;
                } else {
                    width = 0; height = 0; needsProbe = true;
                }
            }
        }
        if (!src || src.startsWith('data:')) continue;

        const lower = [src.toLowerCase(), alt.toLowerCase(), className.toLowerCase()];
        candidates.push({
            src: src,
            srcset: img.srcset || null,
            alt: alt,
            width: width,
            height: height,
            format: formatOf(src),
            position: positionOf(rect),
            containsLogo: matchesAny(lower, ['logo']),
            containsProductKeywords: matchesAny(lower, productKeywords),
            inHeader: inHeader,
            isLazyLoaded: img.hasAttribute('data-src') || img.hasAttribute('loading') || img.hasAttribute('data-lazy'),
            className: className,
            parentTag: img.parentElement ? img.parentElement.tagName.toLowerCase() : null,
            anchorHref: anchorHrefOf(img),
            needsProbe: needsProbe
        });
    }

    // --- channel 2: attribute-declared slider/lazy sources --------------------
    const SOURCE_ATTRS = ['data-img-url', 'data-bg', 'data-background', 'data-background-image', 'data-lazy-src', 'data-large_image'];
    for (const attr of SOURCE_ATTRS) {
        for (const el of Array.from(document.querySelectorAll('[' + attr + ']'))) {
            if (el.tagName === 'IMG') continue; // handled by channel 1
            const url = toAbs(el.getAttribute(attr));
            if (!url || url.startsWith('data:')) continue;
            const rect = el.getBoundingClientRect();
            const className = String(el.className || '');
            const lower = [url.toLowerCase(), className.toLowerCase()];
            candidates.push({
                src: url,
                srcset: null,
                alt: el.getAttribute('alt') || el.getAttribute('title') || '',
                width: 0,
                height: 0,
                format: formatOf(url),
                position: positionOf(rect),
                containsLogo: matchesAny(lower, ['logo']),
                containsProductKeywords: matchesAny(lower, productKeywords),
                inHeader: false,
                isLazyLoaded: true,
                className: className,
                parentTag: attr,
                anchorHref: anchorHrefOf(el),
                needsProbe: true
            });
        }
    }

    // --- channel 3: computed background images (opt-in) -----------------------
    if (includeBackgrounds) {
        for (const el of Array.from(document.querySelectorAll('*'))) {
            const bgImage = window.getComputedStyle(el).backgroundImage;
            if (!bgImage || bgImage === 'none' || !bgImage.includes('url(')) continue;
            const urlMatch = bgImage.match(/url\\(['"]?([^'"]+)['"]?\\)/);
            if (!urlMatch || !urlMatch[1]) continue;
            const url = toAbs(urlMatch[1]);
            if (!url || url.startsWith('data:')) continue;
            const rect = el.getBoundingClientRect();
            candidates.push({
                src: url,
                srcset: null,
                alt: '',
                width: 0,
                height: 0,
                format: 'background',
                position: positionOf(rect),
                containsLogo: url.toLowerCase().includes('logo'),
                containsProductKeywords: false,
                inHeader: false,
                isLazyLoaded: false,
                className: String(el.className || ''),
                parentTag: 'background',
                anchorHref: anchorHrefOf(el),
                needsProbe: true
            });
        }
    }

    // --- dedupe by URL (prefer entries with known dimensions) -----------------
    const bySrc = new Map();
    for (const c of candidates) {
        const prev = bySrc.get(c.src);
        if (!prev || (prev.needsProbe && !c.needsProbe)) bySrc.set(c.src, c);
    }
    const images = Array.from(bySrc.values());

    // --- probe unknown dimensions so width/height are always real pixels ------
    // Chunked so a background-heavy page doesn't fire 150 parallel fetches at the
    // origin, with a global wall-clock budget so probing can't eat the extraction
    // timeout on a slow CDN.
    const MAX_PROBES = 150;
    const PROBE_TIMEOUT_MS = 5000;
    const PROBE_BUDGET_MS = 25000;
    const PROBE_CHUNK = 20;
    const toProbe = images.filter(c => c.needsProbe).slice(0, MAX_PROBES);
    const probeStart = Date.now();
    for (let i = 0; i < toProbe.length; i += PROBE_CHUNK) {
        if (Date.now() - probeStart > PROBE_BUDGET_MS) break;
        await Promise.all(toProbe.slice(i, i + PROBE_CHUNK).map(c => new Promise(resolve => {
            const probe = new Image();
            const finish = () => {
                if (probe.naturalWidth) { c.width = probe.naturalWidth; c.height = probe.naturalHeight; }
                resolve();
            };
            probe.onload = finish;
            probe.onerror = () => resolve();
            setTimeout(resolve, PROBE_TIMEOUT_MS);
            probe.src = c.src;
        })));
    }
    // Candidates still dimensionless get dropped by the size filter — count them
    // so silent losses are visible in metadata.
    const unprobedCount = images.filter(c => c.needsProbe && !c.width).length;
    images.forEach(c => { delete c.needsProbe; });

    const lazyLoadedCount = images.filter(img => img.isLazyLoaded).length;

    return {
        allImages: images,
        pageContext: {
            viewportWidth: viewportWidth,
            viewportHeight: viewportHeight,
            scrollHeight: document.body.scrollHeight
        },
        lazyLoadedCount: lazyLoadedCount,
        unprobedCount: unprobedCount
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
        elif img.get("containsLogo") and img["width"] < 600:
            # No inHeader requirement: footer/group logos and srcset-upgraded header
            # logos (probed at full size, often 300-500px wide) are still logos.
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
                "anchorHref": img.get("anchorHref"),
            }
        )
    return result


async def prepare_and_extract(
    page,
    url: str,
    *,
    min_width: int,
    min_height: int,
    max_images: int = 100,
    include_backgrounds: bool = False,
    nav_timeout_ms: int | None = None,
) -> dict:
    """Navigate an already-created page to `url`, prepare it (consent, animations,
    scroll, lazy loads) and run the in-browser extraction. Shared by the single-page
    endpoint and the site crawler — the caller owns page/context lifecycle."""
    nav_timeout = nav_timeout_ms or settings.screenshot_page_navigation_timeout
    logger.info("Navigating to %s for image extraction...", url)

    await page.goto(url, wait_until="commit", timeout=nav_timeout)
    logger.info("Navigation committed, waiting for load state...")

    try:
        await page.wait_for_load_state("load", timeout=30000)
        logger.info("Load state reached")
    except Exception:
        logger.info("Load state timeout (30s), continuing...")

    # Consent overlays lock body scroll (starving lazy loaders below the fold) and
    # reveal-animated sliders only set their background-image once "shown" — clear
    # both before scrolling.
    await dismiss_consent(page)
    await neutralize_animations(page)

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

    # Auto-scroll to trigger lazy loaders
    await page.evaluate(AUTO_SCROLL_JS)

    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        logger.info("Network idle timeout after scroll, continuing...")

    await page.evaluate(WAIT_FOR_IMAGES_JS)

    # Post-load delay. Its own setting, not the screenshot's: everything above has already
    # run — two `networkidle` waits, the full auto-scroll, wait-for-images — so this is the
    # margin for a DOM that is still mutating after all of that, not the settling time a
    # photograph needs. Borrowing the screenshot's 5s spent 40 seconds asleep across an
    # 8-page crawl.
    post_load = settings.extraction_post_load_delay
    if post_load > 0:
        safe_delay = min(post_load, 10000)
        logger.info("Waiting %dms for dynamic content...", safe_delay)
        await asyncio.sleep(safe_delay / 1000)

    # Extract image data using the in-browser JS
    logger.info("Extracting image data...")
    image_data = await page.evaluate(EXTRACT_IMAGES_JS, include_backgrounds)

    all_images = image_data["allImages"]
    page_context = image_data["pageContext"]

    logger.info("Extracted %d total images", len(all_images))

    filtered = _filter_images(all_images, min_width, min_height)
    logger.info("After filtering: %d images", len(filtered))

    limited = filtered[:max_images]
    classified = _classify_images(limited, page_context)

    return {
        "images": classified,
        "filtered_count": len(all_images) - len(filtered),
        "lazy_loaded_count": image_data["lazyLoadedCount"],
        "unprobed_dropped": image_data.get("unprobedCount", 0),
    }


async def extract_images(
    url: str,
    min_width: int | None = None,
    min_height: int | None = None,
    max_images: int = 100,
    include_backgrounds: bool | None = None,
) -> dict:
    if min_width is None:
        min_width = settings.image_min_width
    if min_height is None:
        min_height = settings.image_min_height
    if include_backgrounds is None:
        include_backgrounds = settings.image_include_backgrounds

    overall_timeout = settings.image_extraction_timeout / 1000
    start = time.time()

    async def _do_extract() -> dict:
        context = await browser_pool.acquire_context()
        try:
            page = await context.new_page()
            return await prepare_and_extract(
                page,
                url,
                min_width=min_width,
                min_height=min_height,
                max_images=max_images,
                include_backgrounds=include_backgrounds,
            )
        finally:
            await browser_pool.release_context(context)

    try:
        result = await asyncio.wait_for(_do_extract(), timeout=overall_timeout)
    except asyncio.TimeoutError:
        logger.error("Image extraction timed out after %ds", overall_timeout)
        raise

    elapsed = int((time.time() - start) * 1000)

    return {
        "images": result["images"],
        "metadata": {
            "processingTime": elapsed,
            "totalImages": len(result["images"]),
            "filteredOut": result["filtered_count"],
            "lazyLoadedCount": result["lazy_loaded_count"],
            "unprobedDropped": result["unprobed_dropped"],
            "elapsedMs": elapsed,
        },
    }
