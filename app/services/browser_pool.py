import asyncio
import logging

from patchright.async_api import Browser, BrowserContext, async_playwright

from app.config import settings

logger = logging.getLogger(__name__)

BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
    "--disable-blink-features=AutomationControlled",
]


class BrowserPool:
    def __init__(self) -> None:
        self._playwright = None
        self._browser: Browser | None = None
        self._semaphore = asyncio.Semaphore(settings.screenshot_max_concurrent)
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        await self._launch_browser()
        logger.info("Browser pool started (max concurrent contexts: %d)", settings.screenshot_max_concurrent)

    async def _launch_browser(self) -> None:
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            channel="chrome",
            args=BROWSER_ARGS,
        )
        logger.info("Chrome browser launched")

    async def _ensure_browser(self) -> None:
        async with self._lock:
            if self._browser is None or not self._browser.is_connected():
                logger.warning("Browser disconnected, relaunching...")
                try:
                    if self._browser:
                        await self._browser.close()
                except Exception:
                    pass
                await self._launch_browser()

    async def acquire_context(self) -> BrowserContext:
        await self._semaphore.acquire()
        try:
            for attempt in range(2):
                await self._ensure_browser()
                try:
                    context = await self._browser.new_context(
                        viewport={"width": 1920, "height": 1080},
                        user_agent=(
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/131.0.0.0 Safari/537.36"
                        ),
                    )
                    return context
                except Exception:
                    if attempt == 0:
                        logger.warning("Context creation failed, relaunching browser...")
                        async with self._lock:
                            try:
                                if self._browser:
                                    await self._browser.close()
                            except Exception:
                                pass
                            self._browser = None
                        continue
                    raise
        except Exception:
            self._semaphore.release()
            raise

    async def release_context(self, context: BrowserContext) -> None:
        try:
            await context.close()
        except Exception as e:
            logger.debug("Context already closed: %s", e)
        finally:
            self._semaphore.release()

    async def stop(self) -> None:
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright:
            await self._playwright.stop()
        logger.info("Browser pool stopped")


browser_pool = BrowserPool()
