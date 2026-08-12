"""Shared page-preparation helpers for screenshot, image extraction and crawling.

Two capture-quality problems this module solves:

1. Consent banners (Cookiebot, OneTrust, …) overlay the hero AND set
   `overflow: hidden` on <body>, which silently breaks both auto-scroll and
   full-page capture. `dismiss_consent` clicks the accept button when it can
   (so the choice persists in the browser context across pages) and falls back
   to CSS-hiding known containers + restoring scroll. Substring matching for
   unknown banners runs through `CONSENT_HIDE_WILDCARD_JS`, never the CSS —
   see the comment there for the page it blanked when it did.

2. Scroll-reveal animation frameworks (AOS, WOW, ScrollReveal, sal.js, …) keep
   elements at `opacity: 0` until they enter the viewport. A headless capture
   that hasn't triggered every reveal renders those sections as blank bands.
   `neutralize_animations` force-shows all of them with injected CSS.
"""

import logging

logger = logging.getLogger(__name__)

# Ordered accept-button selectors for the major consent-management platforms,
# most specific first. Clicking (vs hiding) is preferred: the consent cookie
# persists in the browser context, so subsequent pages never show the banner.
CONSENT_CLICK_JS = """() => {
    const SELECTORS = [
        '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll',  // Cookiebot
        '#CybotCookiebotDialogBodyButtonAccept',                    // Cookiebot (older)
        '#onetrust-accept-btn-handler',                             // OneTrust
        '#didomi-notice-agree-button',                              // Didomi
        '.qc-cmp2-summary-buttons button[mode="primary"]',          // Quantcast
        '.cmplz-accept',                                            // Complianz
        '.cky-btn-accept',                                          // CookieYes
        '.osano-cm-accept-all',                                     // Osano
        '.cc-allow, .cc-btn.cc-allow',                              // cookieconsent
        'button[aria-label*="accept" i]',
        'button[id*="accept" i][id*="cookie" i]',
    ];
    const isVisible = (el) => {
        if (!el) return false;
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 &&
               style.visibility !== 'hidden' && style.display !== 'none';
    };
    for (const sel of SELECTORS) {
        let el = null;
        try { el = document.querySelector(sel); } catch (e) { continue; }
        if (isVisible(el)) {
            el.click();
            return sel;
        }
    }
    return null;
}"""

# Fallback for banners that appear late or whose button we can't click. Hiding
# alone is not enough: consent tools lock body scroll, so overflow must be
# restored or auto-scroll and full-page capture see a one-viewport-tall page.
CONSENT_HIDE_CSS = """
#CybotCookiebotDialog, #CybotCookiebotDialogBodyUnderlay,
#onetrust-consent-sdk, #didomi-host, .qc-cmp2-container,
#cmplz-cookiebanner-container, .cky-consent-container, .osano-cm-window,
.cc-window, #cookie-notice, #cookie-law-info-bar,
.cookie-banner {
    display: none !important;
}
html, body {
    overflow: auto !important;
}
"""

# The substring selectors used to live in the CSS above, and one of them cost us every
# capture of an Enfold WordPress site (zhg.co.il, 2026-08-12). Its document root carries
# `class="... av-cookies-no-cookie-consent ..."` — a flag meaning the page needs NO consent
# banner — and `[class*="cookie-consent" i]` matched it. `display: none` on <html> blanks
# the whole document: a valid JPEG, correct dimensions, 2,073,600 identical white pixels.
#
# Nothing noticed, because the page still answered every question we asked it. `innerText`
# on an element that is not being rendered falls back to `textContent` per spec, so text
# extraction returned the full 20,000 characters off a page that drew nothing — and the
# vision model downstream, handed an empty frame and a domain name, invented a brand.
#
# Substring matching earns its place: it catches banners no list of IDs will. So it stays,
# behind a guard. Never the root, never the body, and never an element that contains the
# site's own landmarks — a consent banner does not wrap your header, nav and main content.
CONSENT_HIDE_WILDCARD_JS = """() => {
    const WILDCARD = '[id*="cookie-banner" i], [class*="cookie-consent" i]';
    const LANDMARKS = 'main, #main, header, footer, nav, [role="main"], #wrap_all, #page';
    const hidden = [];
    let candidates = [];
    try {
        candidates = Array.from(document.querySelectorAll(WILDCARD));
    } catch (e) {
        return hidden;
    }
    const landmarks = Array.from(document.querySelectorAll(LANDMARKS));
    for (const el of candidates) {
        if (el === document.documentElement || el === document.body) continue;
        if (landmarks.some(l => el !== l && el.contains(l))) continue;
        el.style.setProperty('display', 'none', 'important');
        hidden.push(`${el.tagName}#${el.id || '-'}.${(el.className || '').toString().slice(0, 40)}`);
    }
    return hidden;
}"""

REVEAL_NEUTRALIZE_CSS = """
[data-aos], [data-aos] *, .aos-init, .aos-animate,
.wow, .animated, .animate-on-scroll, .reveal, .fade-in, .fade-up,
[data-sr-id], .sal-animate, [data-sal] {
    opacity: 1 !important;
    transform: none !important;
    visibility: visible !important;
    animation: none !important;
    transition: none !important;
}
"""

AUTO_SCROLL_JS = """async () => {
    await new Promise((resolve) => {
        const viewportHeight = window.innerHeight;
        const distance = Math.floor(viewportHeight * 0.8);
        const maxHeight = 15000;
        const scrollTimeout = 40000;
        const startTime = Date.now();
        let totalHeight = 0;

        const timer = setInterval(() => {
            const scrollHeight = document.body.scrollHeight;
            window.scrollBy(0, distance);
            totalHeight += distance;

            if (totalHeight >= scrollHeight - viewportHeight || totalHeight >= maxHeight || Date.now() - startTime >= scrollTimeout) {
                clearInterval(timer);
                window.scrollTo(0, 0);
                resolve();
            }
        }, 200);
    });
}"""

WAIT_FOR_IMAGES_JS = """async () => {
    const images = Array.from(document.querySelectorAll('img'));
    await Promise.all(images.map(img => {
        if (img.complete) return;
        return new Promise(resolve => {
            img.addEventListener('load', resolve);
            img.addEventListener('error', resolve);
            setTimeout(resolve, 3000);
        });
    }));
}"""


async def dismiss_consent(page) -> bool:
    """Click the first visible consent-accept button, then CSS-hide known consent
    containers as a fallback (and restore body scroll). Never raises."""
    clicked = None
    try:
        clicked = await page.evaluate(CONSENT_CLICK_JS)
        if clicked:
            logger.info("Consent banner accepted via %s", clicked)
    except Exception as e:
        logger.debug("Consent click attempt failed: %s", e)
    try:
        await page.add_style_tag(content=CONSENT_HIDE_CSS)
    except Exception as e:
        logger.debug("Consent hide CSS injection failed: %s", e)
    try:
        hidden = await page.evaluate(CONSENT_HIDE_WILDCARD_JS)
        if hidden:
            logger.info("Consent containers hidden by substring match: %s", ", ".join(hidden))
    except Exception as e:
        logger.debug("Consent wildcard hide failed: %s", e)
    return bool(clicked)


async def neutralize_animations(page) -> None:
    """Force scroll-reveal-animated elements visible so captures don't show blank
    bands where AOS/WOW/ScrollReveal content hasn't triggered. Never raises."""
    try:
        await page.add_style_tag(content=REVEAL_NEUTRALIZE_CSS)
    except Exception as e:
        logger.debug("Animation neutralize CSS injection failed: %s", e)
