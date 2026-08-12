"""What the endpoint does when a capture comes back empty.

The route already retried — but only when the capture *raised*, and an empty frame raises
nothing: the JPEG is valid, it simply has no page in it. So the one retry that existed was
never spent on the failure that actually happened (zhg.co.il, 2026-08-12).

Two decisions are pinned here, and they pull in opposite directions on purpose:

  * a blank capture is worth the retry, because a fresh page load is a different attempt
    from the second frame the capture itself already took;
  * a blank capture is NOT an error, because `pageText` comes from the same page load and
    for a bot-protected site it is the caller's only first-party evidence about the
    company. Withholding the response to punish the image throws that away too.

So it goes back with `success: true` and `blank: true`, and the caller decides what the
image is good for.
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.requests import ScreenshotRequest  # noqa: E402
from app.routes import screenshot as route  # noqa: E402
from app.services.screenshot_service import CaptureResult  # noqa: E402

URL = "https://zhg.co.il/"
TEXT = "צמח המרמן בע\"מ — יזמות ובנייה"


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    """The route sleeps 2s between attempts; the test has no interest in waiting."""
    monkeypatch.setattr(route, "_RETRY_BACKOFF_S", 0)


@pytest.fixture(autouse=True)
def _fake_upload(monkeypatch):
    async def _upload(image, fmt="png"):
        return {
            "url": f"https://storage.example/shot.{fmt}",
            "fileName": f"shot.{fmt}",
            "fileSize": len(image),
            "contentType": f"image/{fmt}",
        }

    monkeypatch.setattr(route.storage_service, "upload_screenshot", _upload)


def _captures(monkeypatch, *outcomes):
    """Program `capture_screenshot` to produce `outcomes` in order.

    Each outcome is a CaptureResult to return or an exception to raise. Records how many
    attempts were actually made.
    """
    attempts = []

    async def _capture(url, full_page, fmt, quality, delay):
        attempts.append(url)
        outcome = outcomes[min(len(attempts) - 1, len(outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(route, "capture_screenshot", _capture)
    return attempts


def _call():
    body = ScreenshotRequest(url=URL, fullPage=False, format="jpeg", quality=85)
    return asyncio.run(route.screenshot(request=None, body=body))


def _blank():
    return CaptureResult(image=b"\xff" * 100, text=TEXT, blank=True)


def _good():
    return CaptureResult(image=b"\x89PNG-ish" * 20, text=TEXT, blank=False)


class TestABlankCaptureIsRetried:
    def test_a_blank_first_attempt_gets_a_fresh_page_load(self, monkeypatch):
        attempts = _captures(monkeypatch, _blank(), _good())

        result = _call()

        assert len(attempts) == 2, "the blank capture never triggered the retry"
        assert result["blank"] is False
        assert result["success"] is True

    def test_a_good_capture_is_not_retried(self, monkeypatch):
        """The retry is a repair, not a policy — a healthy capture must not pay for it."""
        attempts = _captures(monkeypatch, _good())

        result = _call()

        assert len(attempts) == 1
        assert result["blank"] is False


class TestABlankCaptureIsStillAnAnswer:
    def test_two_blanks_return_flagged_rather_than_failing(self, monkeypatch):
        _captures(monkeypatch, _blank(), _blank())

        result = _call()

        assert result["success"] is True
        assert result["blank"] is True
        # The whole reason this is not an error: the page text survived.
        assert result["pageText"] == TEXT
        assert result["screenshotUrl"].startswith("https://storage.example/")

    def test_a_crash_after_a_blank_keeps_the_blank(self, monkeypatch):
        """Attempt 1 gave us a flawed capture and its page text; attempt 2 blew up.
        Answering 500 would discard evidence we are holding."""
        _captures(monkeypatch, _blank(), RuntimeError("browser disconnected"))

        result = _call()

        assert result["success"] is True
        assert result["blank"] is True
        assert result["pageText"] == TEXT


class TestRealFailuresStillFail:
    def test_two_crashes_are_a_500(self, monkeypatch):
        _captures(monkeypatch, RuntimeError("browser disconnected"))

        result = _call()

        assert result.status_code == 500

    def test_a_timeout_is_a_504(self, monkeypatch):
        _captures(monkeypatch, asyncio.TimeoutError())

        result = _call()

        assert result.status_code == 504

    def test_an_invalid_url_is_rejected_before_any_capture(self, monkeypatch):
        attempts = _captures(monkeypatch, _good())
        body = ScreenshotRequest(url="file:///etc/passwd", fullPage=False, format="jpeg")

        result = asyncio.run(route.screenshot(request=None, body=body))

        assert result.status_code == 400
        assert attempts == []
