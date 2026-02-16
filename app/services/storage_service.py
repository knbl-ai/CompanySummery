import asyncio
import logging
import time
import uuid

from google.cloud.storage import Client as StorageClient
from google.oauth2.service_account import Credentials

from app.config import settings

logger = logging.getLogger(__name__)

CONTENT_TYPE_MAP = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}


class StorageService:
    def __init__(self) -> None:
        self._client: StorageClient | None = None
        self._bucket = None

    def _ensure_client(self) -> None:
        if self._client is not None:
            return
        credentials = Credentials.from_service_account_info(
            {
                "type": "service_account",
                "project_id": settings.gcloud_project_id,
                "client_email": settings.gcloud_client_email,
                "private_key": settings.gcloud_private_key,
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        )
        self._client = StorageClient(
            project=settings.gcloud_project_id,
            credentials=credentials,
        )
        self._bucket = self._client.bucket(settings.gcloud_storage_bucket_name)

    def _generate_filename(self, fmt: str) -> str:
        return f"screenshot-{uuid.uuid4()}-{int(time.time() * 1000)}.{fmt}"

    def _upload_sync(self, buffer: bytes, fmt: str) -> dict:
        self._ensure_client()
        filename = self._generate_filename(fmt)
        content_type = CONTENT_TYPE_MAP.get(fmt, "image/png")
        blob = self._bucket.blob(filename)

        blob.upload_from_string(
            buffer,
            content_type=content_type,
        )
        blob.cache_control = "public, max-age=31536000"
        blob.patch()

        if settings.gcs_public_access:
            blob.make_public()
            url = f"https://storage.googleapis.com/{settings.gcloud_storage_bucket_name}/{filename}"
        else:
            url = blob.generate_signed_url(
                expiration=settings.gcs_signed_url_expiry,
                method="GET",
            )

        return {
            "url": url,
            "fileName": filename,
            "fileSize": len(buffer),
            "contentType": content_type,
        }

    async def upload_screenshot(self, buffer: bytes, fmt: str = "png") -> dict:
        timeout = settings.screenshot_gcs_upload_timeout / 1000
        logger.info("Uploading %d bytes to GCS (timeout: %.0fs)...", len(buffer), timeout)

        result = await asyncio.wait_for(
            asyncio.to_thread(self._upload_sync, buffer, fmt),
            timeout=timeout,
        )

        logger.info("Upload complete: %s", result["fileName"])
        return result


storage_service = StorageService()
