from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Server
    port: int = 8080

    # Google Cloud Storage
    gcloud_project_id: str = ""
    gcloud_storage_bucket_name: str = ""
    gcloud_client_email: str = ""
    gcloud_private_key: str = ""
    gcs_public_access: bool = True
    gcs_signed_url_expiry: int = 3600  # seconds

    # Screenshot timeouts (milliseconds)
    screenshot_request_timeout: int = 300000
    screenshot_operation_timeout: int = 300000
    screenshot_page_navigation_timeout: int = 60000
    screenshot_capture_timeout: int = 60000
    # How long to let the `load` event arrive before giving up on it.
    #
    # It is a head start, not a gate: the readiness poll below is what actually decides
    # whether the page can be photographed, and on the run this was cut for it reported
    # `ready=True` seconds after this wait had expired. Some sites never fire `load` at all
    # — a polling widget, a video, an animation loop keeps the connection open — and there
    # the old 30s was spent in full, every time, to learn nothing. knbl360.com: 30.0s of a
    # 126.1s capture.
    screenshot_load_state_timeout: int = 10000
    screenshot_gcs_upload_timeout: int = 15000

    # Screenshot behavior
    screenshot_max_concurrent: int = 3
    # What is left of the blind pre-capture sleep, now that `FONTS_READY_JS` answers the
    # question it was really being asked (see `page_prep`). It runs after two `networkidle`
    # waits, a full auto-scroll and a wait-for-images, so it is a last settle, not a load.
    screenshot_post_load_delay: int = 1500
    # Bound on the fonts wait — see `screenshot_post_load_delay`.
    screenshot_fonts_ready_timeout: int = 3000

    # Viewport heights a full-page capture may grow to.
    #
    # `fullPage` means "past the fold", not "however far this page happens to run".
    # knbl360.com renders 11441px; capturing all of it cost 29.3s of a 126.1s call and
    # produced an 891KB sliver so tall that the vision model reading brand colours off it
    # downsamples the detail away before it starts. Three viewports is the hero, the first
    # content band and its follow-on — what a person means by "a screenshot of the site".
    screenshot_max_full_page_viewports: int = 3

    # How far the pre-capture scroll walks. The scroll exists to trigger what the capture
    # will SHOW, so it is bounded by the capture — plus a margin, because `PAGE_TEXT_JS`
    # reads the whole body and that text is the caller's only first-party evidence on a
    # site that defeats extraction. Image harvesting keeps the unbounded walk; it is
    # collecting the whole page, not photographing the top of it.
    screenshot_scroll_max_px: int = 6000

    # Rendered pages allowed at once across the whole process. A page is what holds the
    # memory, and it used to be the same count as a context — one page per context — so
    # the context limit above bounded it by accident. Once a crawl renders several at once
    # the two come apart and per-crawl concurrency multiplies with pool concurrency, so
    # this has to be global. Sized for 8Gi: browser baseline plus eight image-heavy pages,
    # which is one crawl's full fan-out plus a screenshot for the analysis running beside it.
    max_concurrent_pages: int = 8

    # Proxy (leave empty to disable)
    proxy_url: str = ""

    # Browser stealth
    browser_locale: str = "en-US"
    browser_timezone: str = "America/New_York"

    # Image extraction
    image_extraction_timeout: int = 120000
    image_min_width: int = 100
    image_min_height: int = 100
    image_include_backgrounds: bool = False
    # Extraction settles differently from a capture. A screenshot is a photograph — a
    # late-arriving hero or a font swap shows in it, so standing still is worth paying for.
    # An extraction only reads the DOM, and by the time it runs the page has already been
    # through two `networkidle` waits, a full auto-scroll and a wait-for-images. Inheriting
    # the screenshot's 5s cost 40 seconds of pure sleeping across an 8-page crawl — 17% of
    # it — waiting on a DOM that had stopped changing.
    extraction_post_load_delay: int = 1000

    # Site crawl (milliseconds)
    crawl_max_pages: int = 8
    crawl_time_budget_ms: int = 240000  # < Cloud Run 300s, leaves serialization headroom
    # Wraps the whole of `prepare_and_extract` — navigation, the consent click, two
    # `networkidle` waits, a full auto-scroll and a wait-for-images — not just the
    # navigation the screenshot path budgets 60s for. At 45s it was the stricter of the
    # two on strictly more work, and knbl360.com lost a whole crawl to it (both start-page
    # attempts timed out) on a page the screenshot leg rendered in the same run, well
    # enough for brand analysis to read four colors off it. Matched to the capture path.
    crawl_page_timeout_ms: int = 60000
    crawl_min_remaining_ms: int = 20000
    # Pages one crawl renders at once, after the start page. Seven discovered pages went
    # 3+3+1 at three; six makes it 6+1, and the wave that is left over is the whole saving
    # — a wave costs its slowest page, not its average. Not seven: that would let a single
    # crawl hold every page slot on the instance, and the screenshot for the analysis it
    # belongs to would queue behind its own crawl. Bounded again by the global
    # `max_concurrent_pages`, which is the limit that protects the instance; this one just
    # decides how much of its own share a single crawl will try to take.
    crawl_page_concurrency: int = 6

    # Rate limiting
    rate_limit: str = "100/15minutes"

    # CORS
    allowed_origins: list[str] = [
        "https://igentity.ai",
        "https://www.igentity.ai",
        "https://socialmediaserveragent.xyz",
        "https://www.socialmediaserveragent.xyz",
    ]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
