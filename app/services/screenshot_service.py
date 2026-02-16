import asyncio
import logging
import time

from app.config import settings
from app.services.browser_pool import browser_pool

logger = logging.getLogger(__name__)

# SPA-aware content readiness check
WAIT_FOR_CONTENT_JS = """async () => {
    const maxWait = 20000;
    const start = Date.now();

    const SPA_SELECTORS = ['#root', '#app', '#__next', '#__nuxt', '[data-reactroot]', 'main'];

    while (Date.now() - start < maxWait) {
        // Check SPA root containers for rendered children with real content
        for (const sel of SPA_SELECTORS) {
            const el = document.querySelector(sel);
            if (el && el.children.length > 0) {
                const text = el.innerText ? el.innerText.trim() : '';
                const imgs = el.querySelectorAll('img[src]:not([src=""])');
                if (text.length > 50 || imgs.length > 1) {
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
        if (bodyText.length > 200 || bodyImgs.length > 3) {
            return {ready: true, textLen: bodyText.length, imgCount: bodyImgs.length, source: 'body'};
        }

        await new Promise(r => setTimeout(r, 500));
    }
    // Timed out — return whatever state we have
    const text = document.body ? document.body.innerText.trim() : '';
    return {ready: false, textLen: text.length, imgCount: document.querySelectorAll('img').length, source: 'timeout'};
}"""

AUTO_SCROLL_JS = """async () => {
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
}"""

WAIT_FOR_IMAGES_JS = """async () => {
    const images = Array.from(document.querySelectorAll('img'));
    await Promise.all(images.map(img => {
        if (img.complete) return;
        return new Promise(resolve => {
            img.addEventListener('load', resolve);
            img.addEventListener('error', resolve);
            setTimeout(resolve, 3000);
        });
    }));
}"""


async def capture_screenshot(
    url: str,
    full_page: bool = True,
    fmt: str = "png",
    quality: int = 90,
    delay: int = 0,
) -> bytes:
    overall_timeout = settings.screenshot_operation_timeout / 1000

    async def _do_capture() -> bytes:
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

            # Capture
            capture_timeout_ms = settings.screenshot_capture_timeout
            screenshot_opts: dict = {
                "full_page": full_page,
                "type": fmt,
                "timeout": capture_timeout_ms,
            }
            if fmt in ("jpeg", "webp"):
                screenshot_opts["quality"] = quality

            logger.info("Capturing screenshot (timeout: %dms)...", capture_timeout_ms)
            buffer = await asyncio.wait_for(
                page.screenshot(**screenshot_opts),
                timeout=capture_timeout_ms / 1000,
            )

            logger.info("Screenshot captured (%d bytes)", len(buffer))
            return buffer
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
