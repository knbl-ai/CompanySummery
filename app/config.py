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

    # Image extraction
    image_extraction_timeout: int = 60000
    image_min_width: int = 100
    image_min_height: int = 100
    image_include_backgrounds: bool = False

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
