import asyncio
import logging
import time
from dataclasses import dataclass

from app.config import settings
from app.services.browser_pool import browser_pool
from app.services.capture_quality import flatness_is_blank, measure_flatness
from app.services.page_prep import (
    AUTO_SCROLL_JS,
    WAIT_FOR_IMAGES_JS,
    dismiss_consent,
    neutralize_animations,
)

logger = logging.getLogger(__name__)

# How long to let the page sit before taking a second frame, when the first one came back
# empty. The page is already loaded by this point, so this buys settling time, not a reload.
_BLANK_RETRY_DELAY_S = 3.0

# Upper bound on returned page text. Consumers truncate far below this for synthesis;
# the cap exists so a pathological page can't bloat the JSON response.
_MAX_PAGE_TEXT_CHARS = 20000

# The rendered text of the page, read at capture time. This browser is the only leg of
# the analysis that gets past a JS challenge (Cloudflare et al.), so for a bot-protected
# site it is the ONLY first-party evidence there is — everything else the caller can
# reach is a web search, i.e. somebody else's account of the company. Runs after the
# scroll and image waits so it reflects what the screenshot actually shows.
PAGE_TEXT_JS = """() => {
    const body = document.body;
    if (!body) return '';
    // innerText (not textContent) so it follows what is VISIBLE — hidden menus,
    // aria-hidden slides and display:none tabs stay out of the company profile.
    const text = body.innerText || '';
    return text.replace(/[ \\t]+/g, ' ').replace(/\\n{3,}/g, '\\n\\n').trim();
}"""


@dataclass
class CaptureResult:
    """A capture is an image AND what the page said — both come from the one page load."""

    image: bytes
    text: str = ""
    # True when the image carries no page at all. Reported rather than raised: the text
    # from this same load is the caller's first-party evidence about the company, and on a
    # bot-protected site it is the ONLY such evidence. Failing the capture to punish the
    # image would throw that away too.
    blank: bool = False


async def _capture_is_blank(image_bytes: bytes, url: str) -> bool:
    """Measure the frame we are about to hand back, off the event loop.

    Decoding is CPU-bound and full-page captures reach 1920x11441; this service runs
    several captures concurrently, so doing it inline would stall the others.
    """
    stats = await asyncio.to_thread(measure_flatness, image_bytes)
    if stats is None or not flatness_is_blank(stats):
        return False
    logger.warning(
        "Capture for %s carries no image: %d bytes, stddev=%.2f, %.1f%% of pixels one tone",
        url, len(image_bytes), stats[0], stats[1] * 100,
    )
    return True


# SPA-aware content readiness check. Counts CSS background-images alongside <img>
# and text — image-led sites (hotels, portfolios) often paint their hero entirely
# via background-image with little text, and without the bgCount signal they poll
# to timeout as "not ready".
WAIT_FOR_CONTENT_JS = """async () => {
    const maxWait = 20000;
    const start = Date.now();

    const SPA_SELECTORS = ['#root', '#app', '#__next', '#__nuxt', '[data-reactroot]', 'main'];

    const countBackgrounds = () => {
        // Bounded probe: this runs every poll iteration, so cap the elements scanned.
        return Array.from(document.querySelectorAll('div,section,figure,a,span,li'))
            .slice(0, 400)
            .filter(el => (window.getComputedStyle(el).backgroundImage || '').includes('url(')).length;
    };

    while (Date.now() - start < maxWait) {
        const bgCount = countBackgrounds();

        // Check SPA root containers for rendered children with real content
        for (const sel of SPA_SELECTORS) {
            const el = document.querySelector(sel);
            if (el && el.children.length > 0) {
                const text = el.innerText ? el.innerText.trim() : '';
                const imgs = el.querySelectorAll('img[src]:not([src=""])');
                if (text.length > 50 || imgs.length > 1 || bgCount > 2) {
                    // Found a rendered SPA root — wait 1s more for async data
                    await new Promise(r => setTimeout(r, 1000));
                    const finalText = el.innerText ? el.innerText.trim() : '';
                    const finalImgs = el.querySelectorAll('img[src]:not([src=""])');
                    return {ready: true, textLen: finalText.length, imgCount: finalImgs.length, source: sel};
                }
            }
        }

        // Fallback: check body for meaningful content (higher threshold)
        const bodyText = document.body ? document.body.innerText.trim() : '';
        const bodyImgs = document.querySelectorAll('img[src]:not([src=""])');
        if (bodyText.length > 200 || bodyImgs.length > 3 || bgCount > 4) {
            return {ready: true, textLen: bodyText.length, imgCount: bodyImgs.length, source: 'body'};
        }

        await new Promise(r => setTimeout(r, 500));
    }
    // Timed out — return whatever state we have
    const text = document.body ? document.body.innerText.trim() : '';
    return {ready: false, textLen: text.length, imgCount: document.querySelectorAll('img').length, source: 'timeout'};
}"""


async def capture_screenshot(
    url: str,
    full_page: bool = True,
    fmt: str = "png",
    quality: int = 90,
    delay: int = 0,
) -> CaptureResult:
    overall_timeout = settings.screenshot_operation_timeout / 1000

    async def _do_capture() -> CaptureResult:
        context = await browser_pool.acquire_context()
        try:
            page = await context.new_page()

            nav_timeout = settings.screenshot_page_navigation_timeout
            logger.info("Navigating to %s (timeout: %dms)...", url, nav_timeout)

            # Use commit — fires earliest, we handle waiting ourselves
            await page.goto(url, wait_until="commit", timeout=nav_timeout)
            logger.info("Navigation committed, waiting for load state...")

            # Wait for load state so JS bundles are fetched
            try:
                await page.wait_for_load_state("load", timeout=30000)
                logger.info("Load state reached")
            except Exception:
                logger.info("Load state timeout (30s), continuing...")

            # Clear consent overlays and force scroll-reveal content visible BEFORE
            # the readiness poll, so it measures the real page, not the banner.
            await dismiss_consent(page)
            await neutralize_animations(page)

            # Wait for real visible content (SPA-aware)
            logger.info("Waiting for visible content to render...")
            content_state = await page.evaluate(WAIT_FOR_CONTENT_JS)
            logger.info("Content state: ready=%s, text=%d chars, images=%d, source=%s",
                        content_state.get("ready"), content_state.get("textLen", 0),
                        content_state.get("imgCount", 0), content_state.get("source", ""))

            # If content not ready, try networkidle then re-check
            if not content_state.get("ready"):
                logger.info("Content not ready, trying networkidle...")
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                content_state = await page.evaluate(WAIT_FOR_CONTENT_JS)
                logger.info("Content state after networkidle: ready=%s, text=%d chars, images=%d",
                            content_state.get("ready"), content_state.get("textLen", 0),
                            content_state.get("imgCount", 0))

            # Auto-scroll to trigger lazy loaders
            logger.info("Scrolling page...")
            await page.evaluate(AUTO_SCROLL_JS)

            # Wait for network to settle after scrolling
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            # Wait for images to finish loading
            await page.evaluate(WAIT_FOR_IMAGES_JS)

            # Post-load delay
            post_load = settings.screenshot_post_load_delay
            total_delay = max(delay, post_load)
            if total_delay > 0:
                safe_delay = min(total_delay, 10000)
                logger.info("Waiting %dms for dynamic content...", safe_delay)
                await asyncio.sleep(safe_delay / 1000)

            # Second consent pass right before capture: CMPs load asynchronously and
            # often appear seconds after `load`. Style tags injected twice are harmless.
            await dismiss_consent(page)
            await neutralize_animations(page)

            # Capture
            capture_timeout_ms = settings.screenshot_capture_timeout
            screenshot_opts: dict = {
                "full_page": full_page,
                "type": fmt,
                "timeout": capture_timeout_ms,
            }
            if fmt in ("jpeg", "webp"):
                screenshot_opts["quality"] = quality

            async def _grab() -> bytes:
                return await asyncio.wait_for(
                    page.screenshot(**screenshot_opts),
                    timeout=capture_timeout_ms / 1000,
                )

            logger.info("Capturing screenshot (timeout: %dms)...", capture_timeout_ms)
            buffer = await _grab()
            logger.info("Screenshot captured (%d bytes)", len(buffer))

            blank = await _capture_is_blank(buffer, url)
            if blank:
                # One more frame of a page that is, by every other measure, ready — so this
                # costs a capture, not a page load. The empty frame does not reproduce
                # outside this runtime, so a second look is the cheapest thing that might
                # work; the flag is what makes the answer honest when it doesn't.
                logger.warning(
                    "Blank capture for %s — settling %.1fs and capturing again", url, _BLANK_RETRY_DELAY_S
                )
                await neutralize_animations(page)
                await asyncio.sleep(_BLANK_RETRY_DELAY_S)
                buffer = await _grab()
                blank = await _capture_is_blank(buffer, url)
                logger.info(
                    "Second capture for %s: %d bytes, blank=%s", url, len(buffer), blank
                )

            # Best-effort: a page that renders but refuses evaluation still yields its
            # screenshot. Text is an addition to the capture, never a condition of it.
            try:
                page_text = await page.evaluate(PAGE_TEXT_JS)
            except Exception as e:
                logger.warning("Page text extraction failed for %s: %s", url, e)
                page_text = ""
            if page_text and len(page_text) > _MAX_PAGE_TEXT_CHARS:
                page_text = page_text[:_MAX_PAGE_TEXT_CHARS]
            logger.info("Page text extracted (%d chars)", len(page_text or ""))

            return CaptureResult(image=buffer, text=page_text or "", blank=blank)
        finally:
            await browser_pool.release_context(context)

    start = time.time()
    try:
        result = await asyncio.wait_for(_do_capture(), timeout=overall_timeout)
        elapsed = int((time.time() - start) * 1000)
        logger.info("Total screenshot time: %dms", elapsed)
        return result
    except asyncio.TimeoutError:
        logger.error("Screenshot operation timed out after %ds", overall_timeout)
        raise
