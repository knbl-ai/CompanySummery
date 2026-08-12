"""Did the capture actually catch a picture of the page?

Live incident 2026-08-12 (zhg.co.il): every capture of the site came back a pure white
1920x1080 frame — 12,998 bytes, standard deviation 0.00, a single tone across 100% of
2,073,600 pixels — while the very same page load returned 20,000 characters of rendered
text. Nothing in this service noticed. Playwright returned a structurally valid JPEG, the
upload succeeded, and the response said `success: true`. The caller then handed that frame
to a vision model asking for the brand's colours, and a model given nothing to look at
answered from the only other thing in its prompt, the domain name: six runs produced six
unrelated companies, each with confident hex codes, each written to the customer's brand
profile where it steered every image generated for them.

The page itself is fine. Captured through this service's exact launch configuration
(`channel="chrome"` plus the six BROWSER_ARGS, he-IL, Asia/Jerusalem), it paints in full on
the first attempt — four configurations out of four, stddev 61 to 84. So the empty frame is
something about this runtime rather than the site, and until that is found the guarantee
has to be narrower and firmer: we never again report an empty frame as a good one.

Thresholds measured against real captures. Working pages scored stddev 61-84, and the
emptiest genuine capture on record — a bot wall — still scored 17.4 with 97.9% of its
pixels in one tone. The broken frames score 0.00 / 100.0%. Both conditions must hold, so a
legitimately minimal page (white background, one small logo) keeps its capture.

Deliberately identical to `screenshot_quality.py` in the consuming repo, which is the
second line of defence. One definition of "blank", enforced in both places — the caller
should not have to re-derive what this service already knows about its own output.
"""

import io
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# A frame this uniform carries no page to look at. Set well below the 17.4 measured on the
# emptiest real capture on record, so only genuinely flat images qualify.
_MAX_BLANK_STDDEV = 3.0

# ...and one tone has to account for essentially every pixel. Real pages, however sparse,
# never reached this: 97.9% was the highest observed.
_MIN_BLANK_TONE_SHARE = 0.99

# Blankness is a property of large flat areas, so full resolution buys nothing. Capping the
# analysed size keeps a full-page capture — these reach 1920x11441 — from costing real time.
_ANALYSIS_MAX_EDGE = 512


def measure_flatness(image_bytes: bytes) -> Optional[Tuple[float, float]]:
    """(stddev, dominant tone share) of the greyscale image, or None if it cannot be read.

    Separate from the verdict so the numbers can be logged: when a capture is rejected the
    log should say how flat it actually was, not merely that it failed.
    """
    if not image_bytes:
        return None
    try:
        from PIL import Image, ImageStat

        with Image.open(io.BytesIO(image_bytes)) as image:
            grey = image.convert("L")
            grey.thumbnail((_ANALYSIS_MAX_EDGE, _ANALYSIS_MAX_EDGE))
            stddev = ImageStat.Stat(grey).stddev[0]
            histogram = grey.histogram()
            total = sum(histogram)
            tone_share = (max(histogram) / total) if total else 0.0
        return stddev, tone_share
    except Exception as e:  # unreadable bytes, truncated buffer, missing decoder
        logger.debug("measure_flatness: could not read image (%s)", e)
        return None


def flatness_is_blank(stats: Tuple[float, float]) -> bool:
    """The verdict on already-measured stats, so a caller that wants both the answer and
    the numbers decodes the image once rather than twice."""
    stddev, tone_share = stats
    return stddev < _MAX_BLANK_STDDEV and tone_share >= _MIN_BLANK_TONE_SHARE


def image_is_blank(image_bytes: bytes) -> bool:
    """Whether `image_bytes` is a flat, contentless frame rather than a rendered page.

    Answers False when the image cannot be read at all: that is a different failure, and
    guessing "blank" here would discard a real capture over a truncated buffer.
    """
    stats = measure_flatness(image_bytes)
    return stats is not None and flatness_is_blank(stats)
