"""Which pages a crawl decides to visit.

The whole of `/crawl-images`'s judgement lives in three pure functions — `_normalize_link`
decides what is even a candidate, `score_page_url` ranks them, `_select_pages` picks. Nothing
here touches a browser, so the suite runs in milliseconds and can be kept honest cheaply.

The case that motivated it: a start URL that is one property's section on a hotel chain's
domain. Host-only filtering plus a root sitemap plus a depth penalty means an unbounded crawl
ranks a SIBLING property above the property it was pointed at, and files its photographs as
the wrong hotel's.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.crawl_service import (  # noqa: E402
    _in_prefix,
    _normalize_link,
    _select_pages,
    score_page_url,
)

BARCELO = "https://www.barcelo.com/en-us/barcelo-budapest/"
BUDAPEST = "/en-us/barcelo-budapest"


def link(href, text="", nav=False):
    return {"href": href, "text": text, "inNav": nav}


# ── _in_prefix ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path,inside", [
    ("/en-us/barcelo-budapest", True),
    ("/en-us/barcelo-budapest/", True),
    ("/en-us/barcelo-budapest/rooms", True),
    ("/en-us/barcelo-budapest/dining/restaurant", True),
    # A hyphen is a boundary too: a FLAT site hangs the property's pages beside it, not under
    # it. Matching only "/" bounded such a crawl to its single start page.
    ("/en-us/barcelo-budapest-rooms", True),
    ("/en-us/barcelo-budapest-partners", True),
    # A different property is still refused — that is what the bound is for. The prefix always
    # names a whole property, never a fragment of one, so "-" cannot reach past it.
    ("/en-us/barcelo-praha", False),
    ("/en-us/barcelo-praha-rooms", False),
    ("/en-us/barcelo", False),
    ("/en-us", False),
    ("/", False),
])
def test_a_section_ends_at_a_slash_or_a_hyphen(path, inside):
    assert _in_prefix(path, BUDAPEST) is inside


def test_an_empty_prefix_contains_everything():
    assert _in_prefix("/anything/at/all", "") is True
    assert _in_prefix("", "") is True


# ── _normalize_link ──────────────────────────────────────────────────────────
def test_only_same_host_http_pages_survive():
    keep = _normalize_link("https://acme.com/rooms", "acme.com")
    assert keep == "https://acme.com/rooms"
    assert _normalize_link("https://www.acme.com/rooms", "acme.com") == (
        "https://www.acme.com/rooms"
    )
    for reject in (
        "https://other.com/rooms", "mailto:a@b.c", "javascript:void(0)",
        "ftp://acme.com/x", "https://acme.com/brochure.pdf", "https://acme.com/hero.jpg",
    ):
        assert _normalize_link(reject, "acme.com") is None, reject


def test_a_fragment_is_dropped_and_a_query_is_kept():
    assert _normalize_link("https://acme.com/rooms#top", "acme.com") == "https://acme.com/rooms"
    assert _normalize_link("https://acme.com/rooms?lang=he", "acme.com") == (
        "https://acme.com/rooms?lang=he"
    )


def test_a_prefix_filters_pages_and_sitemap_entries_alike():
    """Both funnel through this one function, which is why the bound only has to live here."""
    assert _normalize_link(f"{BARCELO}rooms", "barcelo.com", BUDAPEST) is not None
    assert _normalize_link(
        "https://www.barcelo.com/en-us/barcelo-praha/rooms", "barcelo.com", BUDAPEST
    ) is None


def test_a_flat_sites_pages_reach_discovery_too():
    """The property's pages sit beside it on a flat host. Rejecting them here is what left one
    live crawl with a single page to visit."""
    flat = "/play-theatrou-athens"
    for href in (
        "https://www.playhotels.com/play-theatrou-athens-rooms",
        "https://www.playhotels.com/play-theatrou-athens-gallery",
    ):
        assert _normalize_link(href, "playhotels.com", flat) is not None, href
    assert _normalize_link(
        "https://www.playhotels.com/play-acropolis-athens-rooms", "playhotels.com", flat
    ) is None


def test_no_prefix_keeps_the_old_behaviour():
    for href in ("https://acme.com/rooms", "https://acme.com/", "https://acme.com/a/b/c"):
        assert _normalize_link(href, "acme.com") == _normalize_link(href, "acme.com", "")


# ── score_page_url ───────────────────────────────────────────────────────────
def test_content_keywords_outrank_a_bare_page():
    assert score_page_url("https://acme.com/gallery") > score_page_url("https://acme.com/x")


def test_a_negative_keyword_is_vetoed_outright():
    for path in ("/login", "/cart", "/privacy", "/wp-admin/"):
        assert score_page_url(f"https://acme.com{path}", "Rooms and suites") == -100.0


def test_a_foreign_locale_is_penalised_against_the_start_language():
    same = score_page_url("https://acme.com/he/rooms", start_lang="he")
    other = score_page_url("https://acme.com/de/rooms", start_lang="he")
    assert same > other


def test_extra_keywords_extend_rather_than_replace_the_table():
    boosted = score_page_url("https://acme.com/weddings", extra_keywords=["weddings"])
    assert boosted > 0
    # A built-in keyword still scores while a custom list is supplied.
    assert score_page_url("https://acme.com/gallery", extra_keywords=["weddings"]) > 0


def test_depth_is_measured_from_the_crawls_own_root():
    """Without the offset a scoped crawl penalises every page for the prefix it is REQUIRED to
    carry — and since only positive scores survive, a section a few segments deep starves."""
    deep = f"{BARCELO}dining/restaurant"
    assert score_page_url(deep, prefix_depth=2) > score_page_url(deep, prefix_depth=0)
    # No prefix → the offset changes nothing.
    assert score_page_url(deep) == score_page_url(deep, prefix_depth=0)


# ── _select_pages ────────────────────────────────────────────────────────────
CHAIN_LINKS = [
    link(f"{BARCELO}rooms", "Rooms"),
    link(f"{BARCELO}gallery", "Gallery"),
    link(f"{BARCELO}dining/restaurant", "Restaurant"),
    link("https://www.barcelo.com/en-us/barcelo-praha/rooms", "Rooms", nav=True),
    link("https://www.barcelo.com/en-us/spa", "Spa", nav=True),
    link("https://www.barcelo.com/", "Home", nav=True),
]
CHAIN_SITEMAP = [
    "https://www.barcelo.com/en-us/barcelo-madrid/rooms",
    "https://www.barcelo.com/en-us/barcelo-praha/gallery",
    f"{BARCELO}spa",
]


def test_unscoped_a_chain_crawl_wanders_into_other_properties():
    """The regression this suite exists for, and not a hypothetical: most of the page budget
    goes to pages belonging to other properties or to the group."""
    picked = [u for u, _ in _select_pages(BARCELO, CHAIN_LINKS, CHAIN_SITEMAP, 8, None)]
    strays = [u for u in picked if not u.startswith(BARCELO)]
    assert any("barcelo-praha" in u for u in strays)
    assert any("barcelo-madrid" in u for u in strays)   # straight off the root sitemap
    assert len(strays) >= len(picked) / 2, picked


def test_unscoped_a_sibling_property_can_outrank_the_one_we_asked_for():
    """With the tourism keyword set, the nav link to Praha's rooms beats Budapest's own —
    a nav bonus the sibling gets and the property's own deeper page does not."""
    keywords = ["room", "suite", "dining", "spa", "gallery", "pool"]
    ranked = _select_pages(BARCELO, CHAIN_LINKS, [], 8, keywords)
    scores = dict(ranked)
    praha = "https://www.barcelo.com/en-us/barcelo-praha/rooms"
    assert scores[praha] > scores[f"{BARCELO}rooms"]


def test_scoped_the_same_crawl_stays_on_its_own_property():
    picked = [u for u, _ in _select_pages(BARCELO, CHAIN_LINKS, CHAIN_SITEMAP, 8, None, BUDAPEST)]
    assert picked, "a scoped crawl must still find the property's own pages"
    assert all(u.startswith(f"{BARCELO}") for u in picked), picked


def test_a_scoped_crawl_still_reaches_its_deeper_pages():
    picked = [u for u, _ in _select_pages(BARCELO, CHAIN_LINKS, [], 8, None, BUDAPEST)]
    assert f"{BARCELO}dining/restaurant" in picked


def test_sitemap_urls_join_the_candidates_and_obey_the_prefix():
    unscoped = [u for u, _ in _select_pages(BARCELO, [], CHAIN_SITEMAP, 8, None)]
    assert any("barcelo-madrid" in u for u in unscoped)
    scoped = [u for u, _ in _select_pages(BARCELO, [], CHAIN_SITEMAP, 8, None, BUDAPEST)]
    assert scoped == [f"{BARCELO}spa"]


def test_the_start_page_is_never_selected_twice():
    links = CHAIN_LINKS + [link(BARCELO, "Home"), link(BARCELO.rstrip("/"), "Home")]
    for prefix in ("", BUDAPEST):
        picked = [u for u, _ in _select_pages(BARCELO, links, [], 8, None, prefix)]
        assert not any(u.rstrip("/") == BARCELO.rstrip("/") for u in picked)


def test_the_page_budget_is_respected():
    for max_pages in (1, 2, 5):
        picked = _select_pages(BARCELO, CHAIN_LINKS, CHAIN_SITEMAP, max_pages, None)
        assert len(picked) <= max_pages - 1


def test_results_are_ordered_best_first():
    scored = _select_pages(BARCELO, CHAIN_LINKS, CHAIN_SITEMAP, 8, None)
    assert [s for _, s in scored] == sorted((s for _, s in scored), reverse=True)


def test_an_omitted_prefix_and_an_empty_prefix_agree():
    for sitemap in ([], CHAIN_SITEMAP):
        assert _select_pages(BARCELO, CHAIN_LINKS, sitemap, 8, None) == _select_pages(
            BARCELO, CHAIN_LINKS, sitemap, 8, None, ""
        )
