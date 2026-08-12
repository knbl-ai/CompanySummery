"""No consent selector may match the document root.

Live incident 2026-08-12 (zhg.co.il). `CONSENT_HIDE_CSS` carried
`[class*="cookie-consent" i] { display: none !important }`, and the site's Enfold theme
puts this on <html>:

    class="html_stretched responsive ... av-cookies-no-cookie-consent av-default-lightbox ..."

`av-cookies-no-cookie-consent` is Enfold's flag for "this page needs NO consent banner".
It contains the substring `cookie-consent`. The selector matched the document root, and
`display: none` on <html> blanks the whole page.

Every capture of that site for weeks was a pure white 1920x1080 frame — a valid JPEG,
correct dimensions, 2,073,600 identical pixels. Nothing caught it, because the page went
on answering every question we asked: `innerText` on an element that is not being rendered
falls back to `textContent` per spec, so text extraction returned a full 20,000 characters
off a page that drew nothing. Downstream, a vision model was asked for the brand's colours,
had only the domain name to go on, and invented a different company on every run — each one
written into a customer's brand profile.

Substring matching is worth keeping; it catches banners no list of IDs will. What it may
not do is hide the page. These tests pin that: the CSS must not contain a selector capable
of matching the root, and the substring pass must run through the guard instead.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.page_prep import (  # noqa: E402
    CONSENT_HIDE_CSS,
    CONSENT_HIDE_WILDCARD_JS,
    REVEAL_NEUTRALIZE_CSS,
)

# Verbatim from zhg.co.il — the class list that blanked every capture.
ENFOLD_ROOT_CLASS = (
    "html_stretched responsive av-preloader-disabled html_header_top html_logo_right "
    "html_av-overlay-side html_entry_id_15 av-cookies-no-cookie-consent "
    "av-default-lightbox html_text_menu_active avia_desktop js_active avia-chrome"
)


def _selectors(css: str) -> list:
    """Every selector in a stylesheet, one per returned item."""
    out = []
    for block in re.findall(r"([^{}]+)\{[^}]*\}", css):
        out.extend(s.strip() for s in block.split(",") if s.strip())
    return out


def _matches_bare_element(selector: str, tag: str, class_attr: str, id_attr: str = "") -> bool:
    """Whether `selector` matches a lone element with these attributes.

    Only the simple forms this stylesheet uses. A selector containing a combinator is
    scoped to a descendant and so cannot match the root — that is the point of scoping.
    Combinators are looked for OUTSIDE the brackets: the space in `[class*="x" i]` is the
    case-insensitivity flag, and reading it as a descendant combinator made this helper
    answer "scoped, cannot match the root" about the very selector that hid the root.
    """
    if re.search(r"[\s>+~]", re.sub(r"\[[^\]]*\]", "", selector)):
        return False

    classes = class_attr.split()
    for part in re.findall(r"\[[^\]]*\]|[.#]?[\w-]+", selector):
        if part.startswith("[") and "*=" in part:
            attr, value = re.match(r'\[(\w+)\*=\s*"([^"]*)"', part).groups()
            haystack = (class_attr if attr == "class" else id_attr)
            if "i" in part.rsplit('"', 1)[-1]:
                haystack, value = haystack.lower(), value.lower()
            if value not in haystack:
                return False
        elif part.startswith("."):
            if part[1:] not in classes:
                return False
        elif part.startswith("#"):
            if part[1:] != id_attr:
                return False
        elif part not in (tag, "*"):
            return False
    return True


class TestTheRootIsNeverHidden:
    def test_the_live_regression(self):
        """The exact class list, against the exact stylesheet."""
        offenders = [
            s for s in _selectors(CONSENT_HIDE_CSS)
            if _matches_bare_element(s, "html", ENFOLD_ROOT_CLASS)
            and "display" in CONSENT_HIDE_CSS.split(s, 1)[-1][:120]
        ]
        assert offenders == [], f"these would blank the page: {offenders}"

    @pytest.mark.parametrize("css", [CONSENT_HIDE_CSS, REVEAL_NEUTRALIZE_CSS])
    @pytest.mark.parametrize("tag,cls", [("html", ENFOLD_ROOT_CLASS), ("body", ENFOLD_ROOT_CLASS)])
    def test_no_injected_rule_can_select_a_root_element(self, css, tag, cls):
        """Neutralizing animations runs on the same pages and has the same power to
        blank one — `visibility: visible` is harmless, but the selector list is not
        obviously safe forever."""
        hits = [s for s in _selectors(css) if _matches_bare_element(s, tag, cls)]

        # `html, body { overflow: auto }` is deliberate and cannot hide anything.
        assert all("overflow" in css.split(s, 1)[-1][:80] for s in hits), \
            f"{tag} is selected by {hits} for something other than overflow"

    def test_a_real_banner_is_still_caught_by_the_named_selectors(self):
        assert any(
            _matches_bare_element(s, "div", "cky-consent-container")
            for s in _selectors(CONSENT_HIDE_CSS)
        )
        assert any(
            _matches_bare_element(s, "div", "", "onetrust-consent-sdk")
            for s in _selectors(CONSENT_HIDE_CSS)
        )


class TestSubstringMatchingSurvivesButGuarded:
    def test_the_wildcards_moved_rather_than_vanished(self):
        """Deleting them would quietly drop every banner that has no known ID."""
        assert 'cookie-banner' in CONSENT_HIDE_WILDCARD_JS
        assert 'cookie-consent' in CONSENT_HIDE_WILDCARD_JS
        assert '[class*="cookie-consent" i]' not in CONSENT_HIDE_CSS

    def test_the_guard_refuses_the_root_and_the_body(self):
        assert "document.documentElement" in CONSENT_HIDE_WILDCARD_JS
        assert "document.body" in CONSENT_HIDE_WILDCARD_JS

    def test_the_guard_refuses_anything_wrapping_the_page(self):
        """The root was one instance of the general fault: a container that holds the
        site's own landmarks is the page, not a banner."""
        assert "contains(l)" in CONSENT_HIDE_WILDCARD_JS
        for landmark in ("main", "header", "footer", "nav"):
            assert landmark in CONSENT_HIDE_WILDCARD_JS
