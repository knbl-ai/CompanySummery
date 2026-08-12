"""Visiting the discovered pages together, without changing what the crawl returns.

Measured on zhg.co.il before this: 8 pages, 228.8s total, of which the seven pages after
the start page were 130.7s spent strictly one after another. A page visit is mostly
waiting — two `networkidle` waits, an auto-scroll on a 200ms timer, image probes over the
network — and waiting overlaps for free.

Three things had to survive the change, and they are what these tests are about.

**The start page still goes alone.** Its links ARE the discovery, so nothing else can be
selected until it returns; and its consent click has to land in the shared browser context
before any other page opens, or all of them meet the banner again. That was one of the
three reasons the original code gave for being sequential, and it is the one that is real.

**The harvest is the same set.** Which page owns a shared `src`, and which images survive
`max_images`, were decided by the page ranking. Merging as each visit finishes hands those
decisions to whoever loads first, and the same site starts returning different images run
to run. Visits are concurrent; the merge is in rank order.

**Memory is bounded globally.** A page is what holds memory, and per-crawl concurrency
multiplies with pool concurrency — three crawls at three pages each is nine pages on one
4Gi instance. A per-crawl limit cannot see that, so the real bound lives on the pool.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import crawl_service  # noqa: E402

START = "https://zhg.co.il/"
DISCOVERED = [
    "https://zhg.co.il/portfolio-item/achziv",
    "https://zhg.co.il/portfolio-item/saboraim",
    "https://zhg.co.il/portfolio-item/the-lake",
    "https://zhg.co.il/portfolio-item/eyin-gev",
]


class _Tracker:
    """How many pages are mid-render at each moment, and what else was open when each
    one started."""

    def __init__(self):
        self.open_now = 0
        self.peak = 0
        self.started = []  # (url, how many others were already rendering)

    def opened(self, url):
        self.started.append((url, self.open_now))
        self.open_now += 1
        self.peak = max(self.peak, self.open_now)

    def closed(self):
        self.open_now -= 1


class _Page:
    def __init__(self, tracker):
        self._tracker = tracker
        self.url = None

    async def evaluate(self, _js, *_a):
        # Only COLLECT_LINKS_JS reaches a page in this harness.
        return [{"href": u, "text": "", "inNav": True} for u in DISCOVERED]

    async def close(self):
        self._tracker.closed()


class _Context:
    def __init__(self, tracker):
        self._tracker = tracker
        self.request = MagicMock()

    async def new_page(self):
        return _Page(self._tracker)


def _harness(monkeypatch, *, delays=None, images=None, failures=(), tracker=None):
    """Patch away the browser, leaving the crawl's own scheduling exposed."""
    tracker = tracker or _Tracker()
    delays = delays or {}
    images = images or {}
    ctx = _Context(tracker)

    async def _prepare_and_extract(page, url, **_kw):
        # Opened here, closed by the crawl's own `page.close()` in its finally — so the
        # count is the number of pages actually mid-render, on the success path and the
        # failure path alike.
        tracker.opened(url)
        page.url = url
        if url in failures:
            raise RuntimeError(f"render failed: {url}")
        await asyncio.sleep(delays.get(url, 0.05))
        return {"images": list(images.get(url, []))}

    pool = MagicMock()
    pool.acquire_context = AsyncMock(return_value=ctx)
    pool.release_context = AsyncMock()

    slots = asyncio.Semaphore(6)

    class _Slot:
        async def __aenter__(self):
            await slots.acquire()
            return None

        async def __aexit__(self, *_e):
            slots.release()
            return False

    pool.page_slot = lambda: _Slot()

    monkeypatch.setattr(crawl_service, "browser_pool", pool)
    monkeypatch.setattr(crawl_service, "prepare_and_extract", _prepare_and_extract)
    monkeypatch.setattr(crawl_service, "validate_url", lambda _u: (True, None))
    return tracker


def _img(src):
    return {"src": src, "width": 1600, "height": 900, "alt": ""}


async def _crawl(**kw):
    return await crawl_service.crawl_images(START, use_sitemap=False, max_pages=5, **kw)


class TestTheDiscoveredPagesRunTogether:
    @pytest.mark.asyncio
    async def test_more_than_one_page_renders_at_a_time(self, monkeypatch):
        tracker = _harness(monkeypatch, delays={u: 0.1 for u in DISCOVERED})

        await _crawl()

        assert tracker.peak > 1, (
            "pages still render one at a time — 130 of 229 seconds on the measured site"
        )

    @pytest.mark.asyncio
    async def test_the_start_page_renders_alone(self, monkeypatch):
        """Its links are the discovery, and its consent click must land in the shared
        context before any other page opens."""
        tracker = _harness(monkeypatch, delays={u: 0.05 for u in DISCOVERED})

        await _crawl()

        start_events = [(u, n) for u, n in tracker.started if u == START]
        assert start_events, "the start page was never rendered"
        assert all(n == 0 for _u, n in start_events), (
            f"another page was already rendering when the start page began: {tracker.started}"
        )

    @pytest.mark.asyncio
    async def test_no_discovered_page_begins_before_the_start_page_finishes(self, monkeypatch):
        """The strict form of the same rule, from the other side: the consent cookie is
        only in the context once page 1 is done with it."""
        tracker = _harness(monkeypatch, delays={START: 0.15})

        await _crawl()

        first = tracker.started[0][0]
        assert first == START, f"a discovered page rendered first: {tracker.started}"
        assert all(n >= 0 for _u, n in tracker.started)

    @pytest.mark.asyncio
    async def test_fan_out_respects_the_per_crawl_cap(self, monkeypatch):
        monkeypatch.setattr(crawl_service.settings, "crawl_page_concurrency", 2)
        tracker = _harness(monkeypatch, delays={u: 0.1 for u in DISCOVERED})

        await _crawl()

        assert tracker.peak <= 2, f"peak {tracker.peak} exceeded the configured fan-out"

    @pytest.mark.asyncio
    async def test_a_fan_out_of_one_is_still_a_working_crawl(self, monkeypatch):
        """The old behaviour, reachable by configuration — a way back that does not need
        a deploy of different code."""
        monkeypatch.setattr(crawl_service.settings, "crawl_page_concurrency", 1)
        tracker = _harness(
            monkeypatch, images={u: [_img(f"{u}/a.jpg")] for u in DISCOVERED}
        )

        result = await _crawl()

        assert tracker.peak == 1
        assert len(result["images"]) == len(DISCOVERED)


class TestTheHarvestDoesNotDependOnWhoFinishesFirst:
    @pytest.mark.asyncio
    async def test_a_shared_image_is_owned_by_the_higher_ranked_page(self, monkeypatch):
        """The last page is made to finish FIRST. Merging on completion would file the
        shared image under it; rank order files it under the page that outranked it."""
        shared = _img("https://zhg.co.il/shared-hero.jpg")
        _harness(
            monkeypatch,
            delays={DISCOVERED[0]: 0.20, DISCOVERED[-1]: 0.01},
            images={DISCOVERED[0]: [shared], DISCOVERED[-1]: [shared]},
        )

        result = await _crawl()

        owner = next(
            i["pageUrl"] for i in result["images"]
            if i["src"] == "https://zhg.co.il/shared-hero.jpg"
        )
        ranked = [p["url"] for p in result["pages"]]
        assert owner == DISCOVERED[0], f"filed under the fastest page, not the best: {owner}"
        assert ranked.index(DISCOVERED[0]) < ranked.index(DISCOVERED[-1])

    @pytest.mark.asyncio
    async def test_the_image_cap_keeps_the_higher_ranked_pages(self, monkeypatch):
        """`max_images` decides what is dropped. Dropped by completion order it would be
        whichever pages happened to be slow."""
        _harness(
            monkeypatch,
            delays={DISCOVERED[0]: 0.20, DISCOVERED[1]: 0.15},
            images={u: [_img(f"{u}/a.jpg"), _img(f"{u}/b.jpg")] for u in DISCOVERED},
        )

        result = await _crawl(max_images=3)

        srcs = [i["src"] for i in result["images"]]
        assert len(srcs) == 3
        assert srcs[0].startswith(DISCOVERED[0]), f"the top-ranked page lost its place: {srcs}"

    @pytest.mark.asyncio
    async def test_the_cap_still_holds_when_pages_overrun_it(self, monkeypatch):
        """The sequential version stopped visiting once `max_images` was full; this one
        cannot, because the running total is not known until the merge. What must not
        change is the RESULT — the cap is enforced at the merge, so a crawl that renders
        more than it needed still returns exactly what it was asked for."""
        _harness(
            monkeypatch,
            images={u: [_img(f"{u}/{n}.jpg") for n in range(10)] for u in DISCOVERED},
        )

        result = await _crawl(max_images=5)

        assert len(result["images"]) == 5

    @pytest.mark.asyncio
    async def test_pages_are_reported_in_rank_order(self, monkeypatch):
        _harness(
            monkeypatch,
            delays={DISCOVERED[0]: 0.20, DISCOVERED[1]: 0.15, DISCOVERED[2]: 0.10},
        )

        result = await _crawl()

        assert [p["url"] for p in result["pages"]][0] == START
        rest = [p["url"] for p in result["pages"]][1:]
        assert rest == sorted(rest, key=lambda u: DISCOVERED.index(u))

    @pytest.mark.asyncio
    async def test_images_found_counts_what_the_page_actually_contributed(self, monkeypatch):
        """A page whose images were all claimed by a better-ranked page contributed
        nothing, and must not be reported as though it had."""
        shared = _img("https://zhg.co.il/shared.jpg")
        _harness(
            monkeypatch,
            images={DISCOVERED[0]: [shared], DISCOVERED[1]: [shared]},
        )

        result = await _crawl()
        by_url = {p["url"]: p for p in result["pages"]}

        assert by_url[DISCOVERED[0]]["imagesFound"] == 1
        assert by_url[DISCOVERED[1]]["imagesFound"] == 0


class TestFailuresAndBudget:
    @pytest.mark.asyncio
    async def test_one_page_raising_does_not_lose_the_others(self, monkeypatch):
        _harness(
            monkeypatch,
            failures={DISCOVERED[1]},
            images={u: [_img(f"{u}/a.jpg")] for u in DISCOVERED},
        )

        result = await _crawl()

        statuses = {p["url"]: p["status"] for p in result["pages"]}
        assert statuses[DISCOVERED[1]] == "error"
        assert statuses[DISCOVERED[0]] == "ok"
        assert len(result["images"]) == len(DISCOVERED) - 1

    @pytest.mark.asyncio
    async def test_an_exhausted_budget_skips_rather_than_renders(self, monkeypatch):
        """A task queued behind the fan-out can wait out the whole budget. Starting a
        45-second render with five seconds left spends the overrun to produce nothing."""
        monkeypatch.setattr(crawl_service.settings, "crawl_page_concurrency", 1)
        _harness(monkeypatch, delays={u: 0.05 for u in DISCOVERED})

        result = await crawl_service.crawl_images(
            START, use_sitemap=False, max_pages=5, time_budget_ms=120
        )

        assert result["partial"] is True
        assert any(p["status"] == "skipped_budget" for p in result["pages"])

    @pytest.mark.asyncio
    async def test_a_skipped_page_is_still_reported(self, monkeypatch):
        monkeypatch.setattr(crawl_service.settings, "crawl_page_concurrency", 1)
        _harness(monkeypatch, delays={u: 0.05 for u in DISCOVERED})

        result = await crawl_service.crawl_images(
            START, use_sitemap=False, max_pages=5, time_budget_ms=120
        )

        assert [p["url"] for p in result["pages"]][0] == START
        assert len(result["pages"]) == 1 + len(DISCOVERED)


class TestTheMemoryBoundIsGlobal:
    @pytest.mark.asyncio
    async def test_every_render_is_taken_through_a_pool_slot(self, monkeypatch):
        """The bound that protects the instance lives on the pool, not in the crawl — a
        render that skips it is invisible to every other crawl on the box."""
        held = []
        tracker = _Tracker()
        _harness(monkeypatch, tracker=tracker, delays={u: 0.02 for u in DISCOVERED})

        real_slot = crawl_service.browser_pool.page_slot

        def _counting_slot():
            held.append(1)
            return real_slot()

        crawl_service.browser_pool.page_slot = _counting_slot

        await _crawl()

        # start page + every discovered page
        assert len(held) == 1 + len(DISCOVERED)

    def test_the_pool_exposes_a_page_slot(self):
        from app.services.browser_pool import browser_pool

        assert hasattr(browser_pool, "page_slot")

    @pytest.mark.parametrize("module", ["screenshot_service", "image_extraction_service"])
    def test_every_render_path_takes_the_bound(self, module):
        """The crawl is not the only thing that renders. A path that opens a page without
        the slot is invisible to the crawls sharing the instance, and the ceiling stops
        describing the instance — which is the only thing it exists to describe."""
        import importlib

        mod = importlib.import_module(f"app.services.{module}")
        body = mod.__loader__.get_source(mod.__name__)

        assert "new_page()" in body, f"{module} no longer opens a page — update this test"
        assert "page_slot" in body, (
            f"{module} opens a page outside the global bound"
        )

    def test_the_slot_is_always_taken_after_the_context(self):
        """Two locks, one order, everywhere. Reversed in one place they would be a pair of
        callers each holding half of what the other is waiting for."""
        import importlib

        for module in ("screenshot_service", "image_extraction_service", "crawl_service"):
            mod = importlib.import_module(f"app.services.{module}")
            body = mod.__loader__.get_source(mod.__name__)
            ctx = body.index("acquire_context()")
            slot = min(
                (body.index(m) for m in ("acquire_page_slot()", "page_slot():") if m in body),
                default=None,
            )
            assert slot is not None and ctx < slot, (
                f"{module} takes the page slot before the context"
            )

    def test_the_page_bound_is_configured_separately_from_contexts(self):
        from app.config import settings

        assert hasattr(settings, "max_concurrent_pages")
        assert settings.max_concurrent_pages >= settings.screenshot_max_concurrent
