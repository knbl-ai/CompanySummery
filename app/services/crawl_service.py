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

    Segment-boundary match, so `/barcelo-budapest` owns `/barcelo-budapest/rooms` but not
    `/barcelo-budapest-spa-partners`."""
    path = (path or "").rstrip("/")
    prefix = (prefix or "").rstrip("/")
    if not prefix:
        return True
    return path == prefix or path.startswith(prefix + "/")


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
        for child_url in _locs(root, "loc")[:_SITEMAP_MAX_CHILDREN]:
            child = await _fetch_xml(child_url)
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

    async def _visit(page, page_url: str, score: float) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "url": page_url, "status": "ok", "imagesFound": 0,
            "durationMs": 0, "score": score, "screenshotUrl": None, "error": None,
        }
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
            entry["imagesFound"] = _merge_images(page_url, result["images"])
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
        return entry

    context = await browser_pool.acquire_context()
    try:
        # --- page 1: start URL (one retry — its failure fails the whole crawl) ----
        links: list[dict] = []
        start_entry: Optional[dict[str, Any]] = None
        for attempt in (1, 2):
            page = await context.new_page()
            try:
                start_entry = await _visit(page, url, score=0)
                if start_entry["status"] == "ok":
                    links = await page.evaluate(COLLECT_LINKS_JS)
                    break
            finally:
                await page.close()
            if attempt == 1 and start_entry and start_entry["status"] != "ok":
                logger.warning("Start page %s failed (%s), retrying once...", url, start_entry["status"])
        pages.append(start_entry)
        if start_entry["status"] != "ok":
            raise RuntimeError(
                f"Start page failed: {start_entry.get('error') or start_entry['status']}"
            )

        # --- discovery + selection ------------------------------------------------
        sitemap_urls: list[str] = []
        if use_sitemap:
            parts = urlsplit(url)
            sitemap_urls = await _fetch_sitemap_urls(context, f"{parts.scheme}://{parts.netloc}")
            sitemap_used = bool(sitemap_urls)
        selected = _select_pages(
            url, links, sitemap_urls, max_pages, priority_keywords, page_prefix
        )
        logger.info(
            "Crawl %s: discovered %d links, %d sitemap urls; visiting %d pages%s",
            url, len(links), len(sitemap_urls), len(selected),
            f" (scoped to {page_prefix})" if page_prefix else "",
        )

        # --- sequential visits, budget-checked between pages ----------------------
        for page_url, score in selected:
            # SSRF defense in depth (discovery is already same-host-only).
            valid, _reason = validate_url(page_url)
            if not valid:
                continue
            if len(images_by_src) >= max_images:
                break
            if remaining_ms() < settings.crawl_min_remaining_ms:
                partial = True
                pages.append({
                    "url": page_url, "status": "skipped_budget", "imagesFound": 0,
                    "durationMs": 0, "score": score, "screenshotUrl": None, "error": None,
                })
                continue
            page = await context.new_page()
            try:
                pages.append(await _visit(page, page_url, score))
            finally:
                await page.close()
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
