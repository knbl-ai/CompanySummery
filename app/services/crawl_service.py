"""Site crawl: visit the most content-relevant internal pages and aggregate images.

One `/crawl-images` request = one browser context (one pool semaphore slot) visiting
pages SEQUENTIALLY. That keeps peak Chrome memory at ~one rendered page per crawl on
Cloud Run's 4Gi, leaves the other pool slot free for screenshot/extract traffic, and
lets the consent cookie accepted on page 1 suppress the banner on every later page.

Budget exhaustion is normal control flow: the crawl returns everything gathered with
`partial=True` instead of erroring — callers never see a 504 for a slow site.
"""

import asyncio
import logging
import time
from typing import Any, Optional
from urllib.parse import urlsplit
from xml.etree import ElementTree

from app.config import settings
from app.middleware.security import validate_url
from app.services.browser_pool import browser_pool
from app.services.image_extraction_service import prepare_and_extract
from app.services.storage_service import storage_service

logger = logging.getLogger(__name__)

# Page-priority keywords (URL path segments at full weight, link text at 0.8x).
# Generic across industries: covers hospitality (rooms/dining/spa), commerce
# (products/collection), and agency/startup (portfolio/services) vocabularies.
PRIORITY_KEYWORDS: dict[str, float] = {
    "gallery": 10, "photos": 10, "photo": 9, "images": 8, "media": 6,
    "rooms": 9, "suites": 9, "accommodation": 9, "stay": 6,
    "dining": 8, "restaurant": 8, "bar": 6, "spa": 8, "wellness": 8,
    "pool": 7, "beach": 7, "facilities": 7, "amenities": 7,
    "about": 5, "products": 8, "product": 7, "portfolio": 9,
    "projects": 8, "services": 6, "collection": 7, "menu": 5,
    "experience": 6, "activities": 6, "events": 5, "location": 4,
}

NEGATIVE_KEYWORDS = {
    "login", "signin", "register", "cart", "checkout", "account", "privacy",
    "terms", "cookie", "legal", "careers", "sitemap", "feed", "wp-admin",
    "search", "basket", "unsubscribe",
}

# Non-page resources that sometimes appear as internal links.
_SKIP_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
    ".zip", ".doc", ".docx", ".xls", ".xlsx", ".mp4", ".mp3", ".xml", ".rss",
)

COLLECT_LINKS_JS = """() => {
    return Array.from(document.querySelectorAll('a[href]')).map(a => ({
        href: a.href,
        text: (a.innerText || '').trim().slice(0, 120),
        inNav: !!a.closest('nav, header, [role="navigation"]'),
    }));
}"""

_SITEMAP_TIMEOUT_MS = 5000
_SITEMAP_MAX_URLS = 200
_SITEMAP_MAX_CHILDREN = 3


def _norm_host(host: str) -> str:
    return host.lower().removeprefix("www.")


def _in_prefix(path: str, prefix: str) -> bool:
    """Is a page path inside the crawl's section?

    `/` and `-` are both section boundaries: `/barcelo-budapest` owns `/barcelo-budapest/rooms`
    AND `/barcelo-budapest-rooms`. Sites put a property's pages under either — chains that nest
    (barcelo.com) and chains that don't (playhotels.com) are equally common — and matching only
    `/` bounded a flat site's crawl to the single page it started on: one page, one usable photo.

    A sibling property is still refused, which is the point of the bound:
    `/barcelo-praha-rooms` does not extend `/barcelo-budapest`. The caller sends a prefix already
    trimmed to the property's own name, never to a fragment of it, so widening to `-` cannot
    reach past the property."""
    path = (path or "").rstrip("/")
    prefix = (prefix or "").rstrip("/")
    if not prefix:
        return True
    return path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "-")


def _normalize_link(href: str, start_host: str, page_prefix: str = "") -> Optional[str]:
    """Absolute same-host page URL with fragment stripped, or None to discard.

    `page_prefix` bounds the crawl to one section of a host. Host-only filtering is right when
    the host IS the subject and wrong when one host carries a page per subject: a hotel chain
    serves every property off one domain, so crawling from
    `barcelo.com/en-us/barcelo-budapest/` otherwise sweeps in Praha's rooms and the chain's
    spa landing and files them all as Budapest's. Both anchors and sitemap URLs funnel through
    here, so this is the only place the bound has to be applied."""
    try:
        parts = urlsplit(href)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    if _norm_host(parts.netloc) != start_host:
        return None
    path = parts.path or "/"
    if path.lower().endswith(_SKIP_EXTENSIONS):
        return None
    if page_prefix and not _in_prefix(path, page_prefix):
        return None
    normalized = f"{parts.scheme}://{parts.netloc}{path.rstrip('/') or '/'}"
    if parts.query:
        normalized += f"?{parts.query}"
    return normalized


def score_page_url(
    url: str,
    link_text: str = "",
    in_nav: bool = False,
    extra_keywords: Optional[list[str]] = None,
    start_lang: str = "",
    prefix_depth: int = 0,
) -> float:
    parts = urlsplit(url)
    path = parts.path.lower()
    segments = [s for s in path.split("/") if s]
    text = link_text.lower()

    keywords = dict(PRIORITY_KEYWORDS)
    for kw in extra_keywords or []:
        keywords[kw.lower()] = 10

    for neg in NEGATIVE_KEYWORDS:
        if neg in path or neg in text:
            return -100.0

    score = 0.0
    for kw, weight in keywords.items():
        if any(kw in seg for seg in segments):
            score += weight
        if kw in text:
            score += weight * 0.8
    if in_nav:
        score += 3
    # Depth is measured from the crawl's own root. Without the offset a scoped crawl would
    # penalise every page for the prefix it is required to carry — and since only positive
    # scores survive, a section two or three segments deep would starve itself.
    depth = len(segments) - prefix_depth
    if depth > 2:
        score -= 2 * (depth - 2)
    if parts.query:
        score -= 1
    # Locale duplicate: /de/rooms when the start page was /en (or unprefixed).
    if segments and len(segments[0]) == 2 and segments[0].isalpha() and segments[0] != start_lang:
        score -= 5
    return score


async def _fetch_sitemap_urls(context, origin: str) -> list[str]:
    """Best-effort sitemap.xml read via the browser context's HTTP client (inherits
    the stealth UA/cookies, no new dependency). Any failure → empty list."""

    async def _fetch_xml(url: str) -> Optional[ElementTree.Element]:
        try:
            resp = await context.request.get(url, timeout=_SITEMAP_TIMEOUT_MS)
            if not resp.ok:
                return None
            return ElementTree.fromstring(await resp.body())
        except Exception:
            return None

    def _locs(root: ElementTree.Element, tag: str) -> list[str]:
        return [
            el.text.strip()
            for el in root.iter()
            if el.tag.endswith(tag) and el.text and el.text.strip()
        ]

    root = await _fetch_xml(f"{origin}/sitemap.xml")
    if root is None:
        return []
    urls: list[str] = []
    if root.tag.endswith("sitemapindex"):
        # Independent documents on one host. Fetched one after another their 5s timeouts
        # stack into 15s of a budget that has page visits waiting behind it. Gathered in
        # index order, so the resulting URL list is identical to the serial version's.
        children = await asyncio.gather(
            *(_fetch_xml(u) for u in _locs(root, "loc")[:_SITEMAP_MAX_CHILDREN])
        )
        for child in children:
            if child is not None:
                urls.extend(_locs(child, "loc"))
            if len(urls) >= _SITEMAP_MAX_URLS:
                break
    else:
        urls = _locs(root, "loc")
    return urls[:_SITEMAP_MAX_URLS]


def _select_pages(
    start_url: str,
    links: list[dict],
    sitemap_urls: list[str],
    max_pages: int,
    priority_keywords: Optional[list[str]],
    page_prefix: str = "",
) -> list[tuple[str, float]]:
    """Rank discovered internal URLs; returns up to max_pages-1 (url, score) pairs."""
    start_parts = urlsplit(start_url)
    start_host = _norm_host(start_parts.netloc)
    start_segments = [s for s in start_parts.path.split("/") if s]
    start_lang = (
        start_segments[0]
        if start_segments and len(start_segments[0]) == 2 and start_segments[0].isalpha()
        else ""
    )
    start_norm = _normalize_link(start_url, start_host, page_prefix)
    prefix_depth = len([s for s in (page_prefix or "").split("/") if s])

    # Anchor links carry text + nav signals; sitemap URLs score on URL alone.
    candidates: dict[str, tuple[str, bool]] = {}
    for link in links:
        url = _normalize_link(link.get("href") or "", start_host, page_prefix)
        if not url or url == start_norm:
            continue
        prev = candidates.get(url)
        text = link.get("text") or ""
        in_nav = bool(link.get("inNav"))
        if prev is None:
            candidates[url] = (text, in_nav)
        else:
            candidates[url] = (prev[0] or text, prev[1] or in_nav)
    for raw in sitemap_urls:
        url = _normalize_link(raw, start_host, page_prefix)
        if url and url != start_norm and url not in candidates:
            candidates[url] = ("", False)

    scored = [
        (url, score_page_url(url, text, in_nav, priority_keywords, start_lang, prefix_depth))
        for url, (text, in_nav) in candidates.items()
    ]
    ranked = sorted(
        (item for item in scored if item[1] > 0),
        key=lambda item: (-item[1], len(urlsplit(item[0]).path)),
    )
    return ranked[: max(0, max_pages - 1)]


async def crawl_images(
    url: str,
    *,
    max_pages: Optional[int] = None,
    max_images: int = 200,
    min_width: int = 100,
    min_height: int = 100,
    include_backgrounds: bool = True,
    priority_keywords: Optional[list[str]] = None,
    include_screenshots: bool = False,
    use_sitemap: bool = True,
    page_prefix: Optional[str] = None,
    time_budget_ms: Optional[int] = None,
) -> dict:
    max_pages = max_pages or settings.crawl_max_pages
    page_prefix = (page_prefix or "").rstrip("/")
    time_budget_ms = time_budget_ms or settings.crawl_time_budget_ms
    start_ts = time.time()

    def remaining_ms() -> float:
        return time_budget_ms - (time.time() - start_ts) * 1000

    images_by_src: dict[str, dict] = {}
    pages: list[dict[str, Any]] = []
    partial = False
    sitemap_used = False

    def _merge_images(page_url: str, extracted: list[dict]) -> int:
        fresh = 0
        for img in extracted:
            if len(images_by_src) >= max_images:
                break
            src = img.get("src")
            if not src or src in images_by_src:
                continue
            images_by_src[src] = {**img, "pageUrl": page_url}
            fresh += 1
        return fresh

    async def _visit(page, page_url: str, score: float) -> tuple[dict[str, Any], list[dict]]:
        """Render one page and return its entry plus the images it yielded.

        The images are RETURNED rather than merged here. Merging is what decides which
        page owns a shared `src` and which images survive `max_images`, and doing it as
        each visit finishes would hand those decisions to whichever page happened to load
        first. The caller merges in rank order instead, so the harvest is the same set
        whether the pages ran one at a time or all at once.
        """
        entry: dict[str, Any] = {
            "url": page_url, "status": "ok", "imagesFound": 0,
            "durationMs": 0, "score": score, "screenshotUrl": None, "error": None,
        }
        images: list[dict] = []
        page_start = time.time()
        per_page_ms = min(settings.crawl_page_timeout_ms, remaining_ms() - 10000)
        try:
            result = await asyncio.wait_for(
                prepare_and_extract(
                    page,
                    page_url,
                    min_width=min_width,
                    min_height=min_height,
                    max_images=max_images,
                    include_backgrounds=include_backgrounds,
                ),
                timeout=max(per_page_ms, 5000) / 1000,
            )
            images = result["images"]
            if include_screenshots:
                try:
                    buffer = await page.screenshot(type="jpeg", quality=70, full_page=False)
                    upload = await storage_service.upload_screenshot(buffer, "jpeg")
                    entry["screenshotUrl"] = upload.get("url")
                except Exception as e:
                    logger.warning("Crawl page screenshot failed for %s: %s", page_url, e)
        except asyncio.TimeoutError:
            entry["status"] = "timeout"
        except Exception as e:
            entry["status"] = "error"
            entry["error"] = str(e)[:200]
        entry["durationMs"] = int((time.time() - page_start) * 1000)
        return entry, images

    context = await browser_pool.acquire_context()
    try:
        # The sitemap needs the host and nothing else — not page 1's links, not even
        # whether page 1 loaded — so it has no reason to wait for it. Run serially it was
        # up to 20s (four documents at a 5s timeout) of a budget with page visits queued
        # behind it, spent in the gap between rendering the start page and rendering the
        # rest. Started here it costs whatever exceeds page 1's own duration, which on
        # every site measured so far is nothing at all.
        sitemap_task: Optional[asyncio.Task] = None
        if use_sitemap:
            parts = urlsplit(url)
            sitemap_task = asyncio.create_task(
                _fetch_sitemap_urls(context, f"{parts.scheme}://{parts.netloc}")
            )

        # --- page 1: start URL (one retry — its failure fails the whole crawl) ----
        links: list[dict] = []
        start_entry: Optional[dict[str, Any]] = None
        for attempt in (1, 2):
            async with browser_pool.page_slot():
                page = await context.new_page()
                try:
                    start_entry, start_images = await _visit(page, url, score=0)
                    if start_entry["status"] == "ok":
                        links = await page.evaluate(COLLECT_LINKS_JS)
                        start_entry["imagesFound"] = _merge_images(url, start_images)
                        break
                finally:
                    await page.close()
            if attempt == 1 and start_entry and start_entry["status"] != "ok":
                logger.warning("Start page %s failed (%s), retrying once...", url, start_entry["status"])
        pages.append(start_entry)
        if start_entry["status"] != "ok":
            # The context is about to be torn down under us; a sitemap fetch still in
            # flight would fail into the void and be reported as an unretrieved exception
            # on a crawl that ended for an entirely different, well-reported reason.
            if sitemap_task is not None:
                sitemap_task.cancel()
            raise RuntimeError(
                f"Start page failed: {start_entry.get('error') or start_entry['status']}"
            )

        # --- discovery + selection ------------------------------------------------
        sitemap_urls: list[str] = []
        if sitemap_task is not None:
            sitemap_urls = await sitemap_task
            sitemap_used = bool(sitemap_urls)
        selected = _select_pages(
            url, links, sitemap_urls, max_pages, priority_keywords, page_prefix
        )
        logger.info(
            "Crawl %s: discovered %d links, %d sitemap urls; visiting %d pages%s",
            url, len(links), len(sitemap_urls), len(selected),
            f" (scoped to {page_prefix})" if page_prefix else "",
        )

        # --- concurrent visits, budget-checked as each one starts -----------------
        #
        # These pages were visited one at a time until the timings said what that cost:
        # seven pages, 130.7 of a 228.8-second crawl, almost none of it computing. A page
        # visit is mostly waiting — two `networkidle` waits, an auto-scroll on a timer,
        # image probes over the network — and waiting is the one thing that overlaps for
        # free. The start page still goes alone, before and by itself: its links ARE the
        # discovery, and its consent click has to land in the shared context before any
        # other page opens, or every one of them meets the banner again.
        #
        # Fan-out is bounded twice. `crawl_page_concurrency` is this crawl's own appetite;
        # `browser_pool.page_slot()` is the instance's memory, held globally because three
        # crawls each rendering three pages is nine pages on one 4Gi box, and no per-crawl
        # number can see that.
        fanout = asyncio.Semaphore(max(1, settings.crawl_page_concurrency))

        def _skipped(page_url: str, score: float) -> dict[str, Any]:
            return {
                "url": page_url, "status": "skipped_budget", "imagesFound": 0,
                "durationMs": 0, "score": score, "screenshotUrl": None, "error": None,
            }

        async def _visit_one(page_url: str, score: float):
            async with fanout:
                # Re-checked HERE rather than before launching: a task queued behind the
                # semaphore may wait out the rest of the budget, and starting a 45-second
                # render with 5 seconds left spends the whole overrun to produce nothing.
                if remaining_ms() < settings.crawl_min_remaining_ms:
                    return _skipped(page_url, score), []
                async with browser_pool.page_slot():
                    page = await context.new_page()
                    try:
                        return await _visit(page, page_url, score)
                    finally:
                        await page.close()

        runnable = [
            (page_url, score)
            for page_url, score in selected
            # SSRF defense in depth (discovery is already same-host-only).
            if validate_url(page_url)[0]
        ]
        results = await asyncio.gather(
            *(_visit_one(u, s) for u, s in runnable), return_exceptions=True
        )

        # Merged in RANK order, not completion order. Which page owns a shared `src`, and
        # which images survive `max_images`, are decisions this crawl already made when it
        # ranked the pages — letting the network reorder them would make the same site
        # return a different harvest run to run.
        for (page_url, score), outcome in zip(runnable, results):
            if isinstance(outcome, BaseException):
                logger.warning("Crawl page %s raised: %s", page_url, outcome)
                pages.append({
                    "url": page_url, "status": "error", "imagesFound": 0,
                    "durationMs": 0, "score": score, "screenshotUrl": None,
                    "error": str(outcome)[:200],
                })
                continue
            entry, images = outcome
            if entry["status"] == "skipped_budget":
                partial = True
            else:
                entry["imagesFound"] = _merge_images(page_url, images)
            pages.append(entry)
    finally:
        await browser_pool.release_context(context)

    images = list(images_by_src.values())
    return {
        "images": images,
        "pages": pages,
        "partial": partial,
        "metadata": {
            "processingTime": int((time.time() - start_ts) * 1000),
            "pagesDiscovered": len(pages),
            "pagesVisited": sum(1 for p in pages if p["status"] in ("ok", "timeout", "error")),
            "sitemapUsed": sitemap_used,
            "budgetExhausted": partial,
        },
    }
