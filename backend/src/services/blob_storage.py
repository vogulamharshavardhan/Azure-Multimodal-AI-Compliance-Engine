"""Private, short-lived Azure Blob Storage for video ingestion.

Uploaded objects are private and receive a short-lived, read-only HTTPS SAS URL
for Azure Video Indexer ingestion. The caller must delete each temporary blob.
"""
from __future__ import annotations
from dotenv import load_dotenv
load_dotenv()
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.storage.blob import (
    BlobServiceClient,
    BlobSasPermissions,
    ContentSettings,
    generate_blob_sas,
)

from backend.src.core.exceptions import BlobStorageError, ConfigurationError

logger = logging.getLogger(__name__)


class BlobStorageService:
    """Upload, sign, and delete private temporary video blobs."""

    def __init__(self) -> None:
        connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "").strip()
        if not connection_string:
            raise ConfigurationError(
                "AZURE_STORAGE_CONNECTION_STRING is required for temporary video storage."
            )

        self.container_name = os.getenv(
            "AZURE_STORAGE_CONTAINER_NAME", "brand-guardian-temp"
        ).strip().lower()
        if (
            not 3 <= len(self.container_name) <= 63
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?", self.container_name)
        ):
            raise ConfigurationError("AZURE_STORAGE_CONTAINER_NAME is invalid.")

        try:
            self.client = BlobServiceClient.from_connection_string(connection_string)
            self.account_name = self.client.account_name
            self.account_key = self._extract_account_key(connection_string)
            self.container = self.client.get_container_client(self.container_name)
            try:
                self.container.create_container()
            except ResourceExistsError:
                # Reuse the existing container only if it is still private.
                pass
            properties = self.container.get_container_properties()
            public_access = (
                properties.get("public_access")
                if isinstance(properties, dict)
                else getattr(properties, "public_access", None)
            )
            if public_access is not None:
                raise ConfigurationError(
                    "The temporary Azure Blob Storage container must remain private."
                )
        except Exception as exc:
            logger.error(
                "Azure Blob Storage initialization failed. error_type=%s",
                type(exc).__name__,
            )
            raise BlobStorageError(
                "Unable to initialize temporary Azure Blob Storage."
            ) from None

        self.sas_ttl_minutes = self._positive_int("AZURE_STORAGE_SAS_TTL_MINUTES", 60)

    @staticmethod
    def _extract_account_key(connection_string: str) -> str:
        values = {}
        for part in connection_string.split(";"):
            if "=" in part:
                key, value = part.split("=", 1)
                values[key.strip().lower()] = value.strip()
        key = values.get("accountkey")
        if not key:
            raise ConfigurationError(
                "The Azure Storage connection string must include an account key."
            )
        return key

    @staticmethod
    def _positive_int(name: str, default: int) -> int:
        raw = os.getenv(name, str(default)).strip()
        try:
            value = int(raw)
        except ValueError:
            raise ConfigurationError(f"{name} must be an integer.") from None
        if value <= 0:
            raise ConfigurationError(f"{name} must be greater than zero.")
        return value

    def upload_and_create_read_url(self, file_path: str | Path, *, object_prefix: str = "videos") -> tuple[str, str]:
        """Upload a local file and return (blob_name, short-lived read URL)."""
        path = Path(file_path).expanduser().resolve()
        if not path.is_file() or path.stat().st_size <= 0:
            raise BlobStorageError("Temporary video file is missing or empty.")

        safe_prefix = re.sub(r"[^A-Za-z0-9/_-]", "-", object_prefix).strip("/")
        blob_name = f"{safe_prefix}/{uuid.uuid4().hex}/{path.name}"
        blob = self.container.get_blob_client(blob_name)
        uploaded = False
        try:
            with path.open("rb") as stream:
                blob.upload_blob(
                    stream,
                    overwrite=False,
                    content_settings=ContentSettings(content_type="video/mp4"),
                )
            uploaded = True

            now = datetime.now(timezone.utc)
            sas = generate_blob_sas(
                account_name=self.account_name,
                container_name=self.container_name,
                blob_name=blob_name,
                account_key=self.account_key,
                permission=BlobSasPermissions(read=True),
                start=now - timedelta(minutes=5),
                expiry=now + timedelta(minutes=self.sas_ttl_minutes),
                protocol="https",
            )
            url = f"{blob.url}?{sas}"
            logger.info(
                "Temporary video uploaded to private Blob Storage. blob_name=%s size_mb=%.2f sas_ttl_minutes=%d",
                blob_name,
                path.stat().st_size / 1048576,
                self.sas_ttl_minutes,
            )
            return blob_name, url
        except Exception as exc:
            if uploaded:
                try:
                    blob.delete_blob(delete_snapshots="include")
                except Exception:
                    logger.warning(
                        "Failed to remove partially staged temporary blob. blob_name=%s",
                        blob_name,
                    )
            logger.error(
                "Temporary video upload failed. error_type=%s", type(exc).__name__
            )
            raise BlobStorageError(
                "Unable to upload the video to temporary Azure Blob Storage."
            ) from None

    def delete(self, blob_name: str) -> None:
        """Delete a temporary blob. Cleanup failures are logged without SAS data."""
        if not blob_name:
            return
        try:
            self.container.delete_blob(blob_name, delete_snapshots="include")
            logger.info("Temporary video blob deleted. blob_name=%s", blob_name)
        except ResourceNotFoundError:
            # Idempotent cleanup: an already-absent object is considered clean.
            logger.info("Temporary video blob was already absent. blob_name=%s", blob_name)
        except Exception as exc:
            logger.error(
                "Temporary video blob cleanup failed. blob_name=%s error_type=%s",
                blob_name,
                type(exc).__name__,
            )
            raise BlobStorageError(
                "Temporary video cleanup failed. Check the Azure container and retention policy."
            ) from None

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            close()
