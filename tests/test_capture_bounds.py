"""What a full-page capture is allowed to photograph.

`full_page` used to mean "however far this page happens to run". On knbl360.com that was
11441px, 29.3s of a 126.1s call, and an 891KB sliver the vision model downsamples before it
reads a colour off it. The bound only bites on the pages that made it necessary — a short
page is still captured whole, byte for byte as before.
"""

import asyncio

import pytest

from app.config import settings
from app.services.screenshot_service import _full_page_clip


class FakePage:
    """A page that answers the geometry probe, or refuses to."""

    def __init__(self, geom=None, raises=False):
        self._geom = geom
        self._raises = raises

    async def evaluate(self, _script, *_args):
        if self._raises:
            raise RuntimeError("Execution context was destroyed")
        return self._geom


def clip_for(**geom):
    return asyncio.run(_full_page_clip(FakePage(geom)))


class TestFullPageClip:
    def test_a_page_that_fits_the_bound_is_captured_whole(self):
        """Two viewports of page, three viewports of budget — nothing to clip."""
        assert clip_for(scrollHeight=2000, viewportHeight=1080, viewportWidth=1920) is None

    def test_a_page_exactly_at_the_bound_is_captured_whole(self):
        cap = 1080 * settings.screenshot_max_full_page_viewports
        assert clip_for(scrollHeight=cap, viewportHeight=1080, viewportWidth=1920) is None

    def test_a_tall_page_is_clipped_to_the_viewport_multiple(self):
        """The knbl360.com shape: 11441px of page, capped to three viewports."""
        clip = clip_for(scrollHeight=11441, viewportHeight=1080, viewportWidth=1920)
        assert clip == {
            "x": 0,
            "y": 0,
            "width": 1920,
            "height": 1080 * settings.screenshot_max_full_page_viewports,
        }

    def test_the_clip_starts_at_the_top_of_the_page(self):
        """A brand read wants the hero, not a band from the middle of the scroll."""
        clip = clip_for(scrollHeight=50000, viewportHeight=800, viewportWidth=1280)
        assert (clip["x"], clip["y"]) == (0, 0)
        assert clip["width"] == 1280

    def test_a_page_that_refuses_to_be_measured_is_captured_whole(self):
        """Falling back to the old behaviour is never wrong — only sometimes slow."""
        assert asyncio.run(_full_page_clip(FakePage(raises=True))) is None

    @pytest.mark.parametrize(
        "geom",
        [
            {"scrollHeight": 0, "viewportHeight": 1080, "viewportWidth": 1920},
            {"scrollHeight": 11441, "viewportHeight": 0, "viewportWidth": 1920},
            {"scrollHeight": 11441, "viewportHeight": 1080, "viewportWidth": 0},
            {},
        ],
    )
    def test_nonsense_geometry_never_produces_a_clip(self, geom):
        """A zero-width clip is a capture failure, not a smaller capture."""
        assert clip_for(**geom) is None
