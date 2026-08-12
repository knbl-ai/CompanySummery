"""A capture that holds no page must not be reported as a good one.

Live incident 2026-08-12 (zhg.co.il): every capture came back a pure white 1920x1080
frame — 12,998 bytes, stddev 0.00, one tone across 100% of pixels — while the same page
load returned 20,000 characters of rendered text. Playwright raised nothing, the JPEG was
structurally valid, the upload worked, and the response said `success: true`. Downstream,
a vision model asked for the brand's colours and handed an empty frame answered from the
domain name in its prompt: six runs, six unrelated companies, each written into a
customer's brand profile.

The site is not the problem — through this service's exact launch configuration it paints
in full on the first attempt, four configurations out of four. So these tests pin the
narrower promise: whatever the runtime does, an empty frame is measured and declared.

The numbers below are from real captures. Working sites scored stddev 61-84 with the most
common tone covering 12-80% of pixels; even a near-empty bot wall scored 17.4 / 97.9%. The
broken frames scored 0.00 / 100.0%.
"""

import io
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.capture_quality import (  # noqa: E402
    flatness_is_blank,
    image_is_blank,
    measure_flatness,
)


def _jpeg(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def _blank_capture() -> bytes:
    """What this service returned for zhg.co.il, six times running."""
    return _jpeg(Image.new("RGB", (1920, 1080), "white"))


def _rendered_page() -> bytes:
    """A page with actual content: a dark header band and body blocks on white."""
    image = Image.new("RGB", (1920, 1080), "white")
    for box, colour in (
        ((0, 0, 1920, 120), (18, 32, 70)),
        ((80, 200, 900, 640), (40, 90, 160)),
        ((980, 200, 1840, 400), (220, 90, 60)),
        ((80, 720, 1840, 1000), (60, 60, 60)),
    ):
        image.paste(Image.new("RGB", (box[2] - box[0], box[3] - box[1]), colour), box[:2])
    return _jpeg(image)


class TestTheVerdict:
    def test_a_flat_white_frame_is_blank(self):
        assert image_is_blank(_blank_capture()) is True

    def test_a_rendered_page_is_not_blank(self):
        assert image_is_blank(_rendered_page()) is False

    def test_a_sparse_page_keeps_its_capture(self):
        """A white page with one small logo is a minimal design, not a failed capture.

        This is the false positive that costs something real: rejecting it would discard a
        working capture. Modelled on the emptiest genuine frame on record — a bot wall at
        97.9% one tone — and still comfortably clear of the threshold.
        """
        image = Image.new("RGB", (1920, 1080), "white")
        image.paste(Image.new("RGB", (150, 60), (10, 10, 10)), (60, 40))

        assert image_is_blank(_jpeg(image)) is False

    def test_a_solid_dark_frame_is_blank_too(self):
        """Blankness is flatness, not whiteness — a frame that painted only the background
        colour holds no more of the page than a white one."""
        assert image_is_blank(_jpeg(Image.new("RGB", (1920, 1080), (12, 12, 30)))) is True

    def test_unreadable_bytes_are_not_called_blank(self):
        """An image we cannot decode is a different failure. Answering "blank" here would
        throw away a real capture over a truncated buffer."""
        assert image_is_blank(b"this is not an image") is False
        assert image_is_blank(b"") is False

    def test_a_tall_full_page_capture_is_measured_not_refused(self):
        """Real full-page captures run to 11441px; the analysis downsamples."""
        tall = Image.new("RGB", (1920, 9000), "white")
        tall.paste(Image.new("RGB", (1800, 4000), (30, 60, 120)), (60, 500))

        assert image_is_blank(_jpeg(tall)) is False


class TestTheNumbersBehindIt:
    def test_flatness_is_reported_for_the_log(self):
        """When a capture is rejected the log should say how flat it actually was."""
        stddev, tone_share = measure_flatness(_blank_capture())

        assert stddev == pytest.approx(0.0, abs=0.5)
        assert tone_share == pytest.approx(1.0, abs=0.01)

    def test_an_unreadable_image_measures_to_nothing(self):
        assert measure_flatness(b"not an image") is None
        assert measure_flatness(b"") is None

    def test_the_verdict_can_be_taken_on_stats_alone(self):
        """So a caller wanting both the answer and the numbers decodes once, not twice."""
        stats = measure_flatness(_blank_capture())

        assert flatness_is_blank(stats) is True
        assert flatness_is_blank(measure_flatness(_rendered_page())) is False

    def test_both_conditions_must_hold(self):
        """Either alone is too eager: a busy page can be dominated by one tone, and a
        gentle gradient is uniform without being empty."""
        assert flatness_is_blank((0.5, 0.80)) is False  # flat, but three tones in five
        assert flatness_is_blank((40.0, 0.999)) is False  # one tone, but real variation
        assert flatness_is_blank((0.5, 0.999)) is True
