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
    screenshot_gcs_upload_timeout: int = 15000

    # Screenshot behavior
    screenshot_max_concurrent: int = 3
    screenshot_post_load_delay: int = 5000

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
    crawl_page_timeout_ms: int = 45000
    crawl_min_remaining_ms: int = 20000

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
