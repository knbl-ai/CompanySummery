"""Time a crawl spends neither rendering nor reading a page.

Measured against the deployed service, `zhg.co.il`, 8 pages, 120 images:

    sum(page durationMs) = 172.9s
    total processingTime = 228.8s
    ─────────────────────────────
    unaccounted          =  55.9s   ← a quarter of the crawl

Two contributors are pure scheduling, and neither is doing anything a page needs:

1. The sitemap read sits BETWEEN page 1 and the rest, though it needs only the host — up
   to four documents at a 5s timeout each, fetched one after another, while nothing else
   runs. It can start with page 1 and its children can be fetched together.

2. Every page then sleeps a flat 5s at the end of extraction, inherited from the
   screenshot path. A screenshot is a photograph and a late hero shows in it; an
   extraction reads the DOM, after two `networkidle` waits, a full auto-scroll and a
   wait-for-images have already run. Eight pages, 40 seconds asleep.

These tests pin both as properties rather than timings: that the sitemap does not wait for
the page, that its children go out together, and that extraction has its own settle
setting rather than borrowing the capture's.
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.services import crawl_service  # noqa: E402
from app.services.crawl_service import _fetch_sitemap_urls  # noqa: E402

SITEMAP_INDEX = b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://zhg.co.il/sitemap-1.xml</loc></sitemap>
  <sitemap><loc>https://zhg.co.il/sitemap-2.xml</loc></sitemap>
  <sitemap><loc>https://zhg.co.il/sitemap-3.xml</loc></sitemap>
</sitemapindex>"""


def _child(*paths):
    locs = "".join(f"<url><loc>https://zhg.co.il{p}</loc></url>" for p in paths)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locs}</urlset>""".encode()


class _Response:
    def __init__(self, body):
        self._body = body
        self.ok = body is not None

    async def body(self):
        return self._body


class _Request:
    """Stands in for `context.request`, holding each fetch open until released.

    The delay is what makes serial and concurrent distinguishable: three children fetched
    one after another take three delays, fetched together they take one.
    """

    def __init__(self, bodies, delay=0.05):
        self._bodies = bodies
        self._delay = delay
        self.in_flight = 0
        self.peak_in_flight = 0
        self.urls = []

    async def get(self, url, timeout=None):
        self.urls.append(url)
        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self._delay)
            return _Response(self._bodies.get(url))
        finally:
            self.in_flight -= 1


class _Context:
    def __init__(self, request):
        self.request = request


BODIES = {
    "https://zhg.co.il/sitemap.xml": SITEMAP_INDEX,
    "https://zhg.co.il/sitemap-1.xml": _child("/portfolio-item/achziv"),
    "https://zhg.co.il/sitemap-2.xml": _child("/portfolio-item/saboraim"),
    "https://zhg.co.il/sitemap-3.xml": _child("/portfolio-item/the-lake"),
}


class TestSitemapChildrenGoOutTogether:
    @pytest.mark.asyncio
    async def test_the_children_are_fetched_concurrently(self):
        req = _Request(BODIES)

        await _fetch_sitemap_urls(_Context(req), "https://zhg.co.il")

        assert req.peak_in_flight >= 3, (
            "children were fetched one after another — their 5s timeouts stack into 15s "
            "of a budget with page visits queued behind it"
        )

    @pytest.mark.asyncio
    async def test_the_index_is_still_read_before_its_children(self):
        """Concurrency starts below the index — its body is what names the children."""
        req = _Request(BODIES)

        await _fetch_sitemap_urls(_Context(req), "https://zhg.co.il")

        assert req.urls[0] == "https://zhg.co.il/sitemap.xml"
        assert req.peak_in_flight == 3  # the three children, never the index alongside them

    @pytest.mark.asyncio
    async def test_the_urls_come_back_in_index_order(self):
        """Gathering must not reorder the result — page selection ranks on this list, and a
        crawl that picks different pages run to run cannot be reasoned about."""
        req = _Request(BODIES)

        urls = await _fetch_sitemap_urls(_Context(req), "https://zhg.co.il")

        assert urls == [
            "https://zhg.co.il/portfolio-item/achziv",
            "https://zhg.co.il/portfolio-item/saboraim",
            "https://zhg.co.il/portfolio-item/the-lake",
        ]

    @pytest.mark.asyncio
    async def test_one_dead_child_does_not_lose_the_others(self):
        bodies = dict(BODIES)
        bodies["https://zhg.co.il/sitemap-2.xml"] = None

        urls = await _fetch_sitemap_urls(_Context(_Request(bodies)), "https://zhg.co.il")

        assert urls == [
            "https://zhg.co.il/portfolio-item/achziv",
            "https://zhg.co.il/portfolio-item/the-lake",
        ]

    @pytest.mark.asyncio
    async def test_a_missing_sitemap_is_simply_empty(self):
        urls = await _fetch_sitemap_urls(_Context(_Request({})), "https://zhg.co.il")

        assert urls == []


class TestTheSitemapDoesNotWaitForPageOne:
    def test_it_is_started_before_the_start_page_is_visited(self):
        """A property of the source, because reaching it through `crawl_images` needs a
        whole browser. What matters is the ORDER of two statements: the fetch is created
        above the page-1 loop and awaited below it, so page 1 renders while it is in
        flight. Written as a scheduling assertion rather than a timing one — a timing test
        here would be a test about the machine."""
        src = crawl_service.crawl_images.__code__.co_consts
        body = crawl_service.__loader__.get_source(crawl_service.__name__)
        start = body.index("sitemap_task = asyncio.create_task")
        page_one = body.index("# --- page 1: start URL")
        awaited = body.index("sitemap_urls = await sitemap_task")

        assert start < page_one < awaited, (
            "the sitemap read is back inside the gap between page 1 and the rest"
        )
        assert src is not None  # the module compiled; guards against a stale source read

    def test_a_failed_start_page_does_not_orphan_it(self):
        """The start page failing tears the context down. A fetch still in flight then
        fails into the void and is reported against a crawl that ended for a different,
        well-reported reason."""
        body = crawl_service.__loader__.get_source(crawl_service.__name__)
        raise_idx = body.index('f"Start page failed:')
        cancel_idx = body.index("sitemap_task.cancel()")

        assert cancel_idx < raise_idx


class TestExtractionSettlesOnItsOwnTerms:
    def test_it_has_a_setting_separate_from_the_capture(self):
        assert hasattr(settings, "extraction_post_load_delay")
        assert settings.extraction_post_load_delay < settings.screenshot_post_load_delay

    def test_extraction_reads_its_own_setting(self):
        """Borrowing `screenshot_post_load_delay` is the regression — 5s per page, after
        everything that makes a page ready has already run."""
        from app.services import image_extraction_service

        body = image_extraction_service.__loader__.get_source(
            image_extraction_service.__name__
        )
        prepare = body[body.index("async def prepare_and_extract"):]

        assert "settings.extraction_post_load_delay" in prepare
        assert "settings.screenshot_post_load_delay" not in prepare

    def test_the_capture_path_keeps_its_own(self):
        """A screenshot is a photograph — a late-arriving hero or a font swap shows in it.
        This change is about extraction only."""
        from app.services import screenshot_service

        body = screenshot_service.__loader__.get_source(screenshot_service.__name__)

        assert "settings.screenshot_post_load_delay" in body
