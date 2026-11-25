"""Azure AI Video Indexer integration for Brand Guardian.

Uses DefaultAzureCredential for ARM authentication and streams video uploads.
Upload POSTs are deliberately not retried because a timeout can have an
ambiguous outcome. The caller owns and must clean up downloaded video files.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
import time
import traceback
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv
load_dotenv()
import requests
import yt_dlp
from azure.identity import DefaultAzureCredential
from requests.adapters import HTTPAdapter
from requests_toolbelt.multipart.encoder import MultipartEncoder
from urllib3.util.retry import Retry

from backend.src.core.exceptions import ConfigurationError, VideoIndexerError

logger = logging.getLogger(__name__)


class VideoIndexerService:
    ARM_SCOPE = "https://management.azure.com/.default"
    ARM_API_VERSION = "2024-01-01"
    ALLOWED_YOUTUBE_HOSTS = {
        "youtube.com", "www.youtube.com", "m.youtube.com",
        "music.youtube.com", "youtu.be", "www.youtu.be",
    }

    def __init__(self) -> None:
        self.account_id = self._required_env("AZURE_VI_ACCOUNT_ID")
        self.location = self._required_env("AZURE_VI_LOCATION").lower()
        self.subscription_id = self._required_env("AZURE_SUBSCRIPTION_ID")
        self.resource_group = self._required_env("AZURE_RESOURCE_GROUP")
        self.vi_name = self._required_env("AZURE_VI_NAME")
        self.credential = DefaultAzureCredential()

        # Retry idempotent GETs only. Never retry an upload POST automatically.
        retry = Retry(
            total=3, connect=3, read=0, status=3, backoff_factor=1,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
        )
        self.session = requests.Session()
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self._account_token: str | None = None
        self._account_token_expires_at = 0.0
        self.request_timeout = (30, 3600)  # connect, socket inactivity
        self._closed = False

    @staticmethod
    def _required_env(name: str) -> str:
        value = os.getenv(name, "").strip()
        if not value:
            raise ConfigurationError(f"Required environment variable is missing: {name}")
        return value

    def get_access_token(self) -> str:
        """Acquire an ARM token using the configured Azure identity."""
        try:
            return self.credential.get_token(self.ARM_SCOPE).token
        except Exception as exc:
            logger.exception("ARM authentication failed. exception_type=%s", type(exc).__name__)
            raise VideoIndexerError("Unable to authenticate with Azure Resource Manager.") from None

    def get_account_token(self, arm_access_token: str | None = None) -> str:
        """Exchange an ARM token for a cached Video Indexer account token."""
        if self._account_token and time.time() < self._account_token_expires_at:
            return self._account_token

        arm_token = arm_access_token or self.get_access_token()
        url = (
            "https://management.azure.com/subscriptions/"
            f"{self.subscription_id}/resourceGroups/{self.resource_group}"
            "/providers/Microsoft.VideoIndexer/accounts/"
            f"{self.vi_name}/generateAccessToken?api-version={self.ARM_API_VERSION}"
        )
        try:
            response = self.session.post(
                url,
                headers={"Authorization": f"Bearer {arm_token}", "Content-Type": "application/json"},
                json={"permissionType": "Contributor", "scope": "Account"},
                timeout=self.request_timeout,
            )
            response.raise_for_status()
            token = response.json().get("accessToken")
            if not token:
                raise VideoIndexerError("Azure returned an empty Video Indexer access token.")
            self._account_token = str(token)
            self._account_token_expires_at = time.time() + 55 * 60
            return self._account_token
        except requests.RequestException as exc:
            logger.exception("Account-token request failed. exception_type=%s", type(exc).__name__)
            raise VideoIndexerError("Unable to obtain a Video Indexer account token.") from None
        except (ValueError, TypeError, AttributeError):
            raise VideoIndexerError("Video Indexer returned an invalid account-token response.") from None

    @classmethod
    def _validate_youtube_url(cls, url: str) -> None:
        try:
            parsed = urlparse(url)
        except (TypeError, ValueError):
            raise ValueError("A valid YouTube URL is required.") from None
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in cls.ALLOWED_YOUTUBE_HOSTS:
            raise ValueError("Only HTTPS URLs from supported YouTube hosts are accepted.")
        if parsed.username or parsed.password:
            raise ValueError("YouTube URLs must not contain embedded credentials.")
        if parsed.hostname and parsed.hostname.lower().endswith("youtu.be") and not parsed.path.strip("/"):
            raise ValueError("The YouTube short URL is missing its video identifier.")
        if parsed.hostname and "youtube.com" in parsed.hostname.lower():
            if not (parsed.path == "/watch" or parsed.path == "/live" or parsed.path.startswith(("/shorts/", "/embed/"))):
                raise ValueError("The supplied YouTube URL does not identify a supported video.")

    def download_youtube_video(self, url: str, output_path: str | None = None) -> str:
        """Download one YouTube video and return its local filesystem path."""
        self._validate_youtube_url(url)
        output_dir = (
            Path(output_path).expanduser().resolve().parent
            if output_path
            else Path(tempfile.gettempdir()) / "brand_guardian"
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        unique_name = f"video_{int(time.time())}_{os.getpid()}"
        options = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": str(output_dir / f"{unique_name}.%(ext)s"),
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "retries": 3,
            "fragment_retries": 3,
        }
        logger.info("Starting YouTube download.")
        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(url, download=True)
                if not info:
                    raise VideoIndexerError("YouTube did not return video information.")
                candidate = Path(downloader.prepare_filename(info))
                if not candidate.exists() and candidate.with_suffix(".mp4").exists():
                    candidate = candidate.with_suffix(".mp4")
                if not candidate.exists():
                    matches = list(output_dir.glob(f"{unique_name}.*"))
                    if not matches:
                        raise VideoIndexerError("Downloaded video file could not be located.")
                    candidate = matches[0]
                if not candidate.is_file() or candidate.stat().st_size <= 0:
                    raise VideoIndexerError("Downloaded video file is empty or invalid.")
            logger.info("Download completed. file=%s size_mb=%.2f", candidate.name, candidate.stat().st_size / 1048576)
            return str(candidate)
        except Exception as exc:
            logger.error(
                "YouTube download failed. exception_type=%s stack=%s",
                type(exc).__name__,
                "".join(traceback.format_tb(exc.__traceback__)),
            )
            if isinstance(exc, VideoIndexerError):
                raise
            raise VideoIndexerError("Unable to download the supplied YouTube video.") from None

    def upload_video_from_url(self, video_url: str, video_name: str) -> str:
        """Ask Video Indexer to ingest a short-lived private-blob SAS URL.

        The URL is sent only to Azure Video Indexer and is never logged.
        The caller owns deletion of the temporary blob after indexing.
        """
        if not isinstance(video_url, str) or not video_url.startswith("https://"):
            raise VideoIndexerError("A valid HTTPS source URL is required for Video Indexer.")

        safe_name = re.sub(r"[^A-Za-z0-9._ -]", "_", str(video_name)).strip() or "brand-guardian-video"
        token = self.get_account_token()
        endpoint = f"https://api.videoindexer.ai/{self.location}/Accounts/{self.account_id}/Videos"
        params = {
            "accessToken": token,
            "videoUrl": video_url,
            "name": safe_name,
            "privacy": "Private",
            "indexingPreset": "Default",
        }
        logger.info("Starting Video Indexer URL ingestion. video_name=%s", safe_name)
        try:
            response = self.session.post(
                endpoint,
                params=params,
                timeout=self.request_timeout,
            )
            response.raise_for_status()
            payload = response.json()
            video_id = payload.get("id") if isinstance(payload, dict) else None
            if not video_id:
                raise VideoIndexerError("Video Indexer response did not contain a video ID.")
            logger.info("Video Indexer accepted URL ingestion. video_id=%s", video_id)
            return str(video_id)
        except requests.RequestException as exc:
            # Request exceptions can include both the SAS URL and Video Indexer token.
            logger.error("Video Indexer URL ingestion failed. error_type=%s", type(exc).__name__)
            raise VideoIndexerError("Video Indexer could not ingest the temporary video URL.") from None
        except (ValueError, TypeError, AttributeError):
            raise VideoIndexerError("Video Indexer returned an invalid URL-ingestion response.") from None

    def upload_video(self, video_path: str, video_name: str) -> str:
        """Stream an MP4 to Video Indexer without retrying ambiguous POSTs."""
        path = Path(video_path).expanduser()
        if not path.is_file() or path.stat().st_size <= 0:
            raise VideoIndexerError("The video upload file does not exist or is empty.")
        safe_name = re.sub(r"[^A-Za-z0-9._ -]", "_", str(video_name)).strip() or "brand-guardian-video"
        token = self.get_account_token()
        url = f"https://api.videoindexer.ai/{self.location}/Accounts/{self.account_id}/Videos"
        params = {"accessToken": token, "name": safe_name, "privacy": "Private", "indexingPreset": "Default"}
        logger.info("Starting Video Indexer upload. file=%s size_mb=%.2f", path.name, path.stat().st_size / 1048576)
        try:
            with path.open("rb") as stream:
                encoder = MultipartEncoder(fields={"file": (path.name, stream, "video/mp4")})
                response = self.session.post(url, params=params, data=encoder,
                                             headers={"Content-Type": encoder.content_type},
                                             timeout=self.request_timeout)
            response.raise_for_status()
            result = response.json()
            video_id = result.get("id") if isinstance(result, dict) else None
            if not video_id:
                raise VideoIndexerError("Video Indexer upload response did not contain a video ID.")
            logger.info("Video uploaded. video_id=%s", video_id)
            return str(video_id)
        except requests.RequestException as exc:
            # requests exceptions can contain the full URL, including accessToken.
            logger.error("Video upload request failed. exception_type=%s", type(exc).__name__)
            raise VideoIndexerError("Video upload outcome may be ambiguous. Check the Video Indexer library before retrying.") from None
        except (ValueError, TypeError):
            raise VideoIndexerError("Video Indexer returned an invalid upload response.") from None

    def wait_for_processing(self, video_id: str, timeout_seconds: int | None = None, poll_interval: int = 20) -> dict:
        """Poll the indexing endpoint until processing succeeds or fails."""
        if timeout_seconds is None:
            try:
                timeout_seconds = int(os.getenv("VIDEO_INDEXER_TIMEOUT_SECONDS", "1800"))
            except ValueError:
                raise ValueError("VIDEO_INDEXER_TIMEOUT_SECONDS must be an integer.") from None
        if timeout_seconds <= 0 or timeout_seconds > 3600 or poll_interval <= 0:
            raise ValueError("Timeout must be 1-3600 seconds and poll interval must be positive.")
        deadline = time.monotonic() + timeout_seconds
        url = f"https://api.videoindexer.ai/{self.location}/Accounts/{self.account_id}/Videos/{video_id}/Index"
        logger.info("Waiting for Video Indexer processing. video_id=%s", video_id)
        last_state = None
        while time.monotonic() < deadline:
            token = self.get_account_token()
            try:
                response = self.session.get(url, params={"accessToken": token}, timeout=self.request_timeout)
                response.raise_for_status()
                payload = response.json()
            except requests.RequestException as exc:
                logger.error("Processing-status request failed. exception_type=%s", type(exc).__name__)
                raise VideoIndexerError("Unable to retrieve Video Indexer processing status.") from None
            except ValueError:
                raise VideoIndexerError("Video Indexer returned an invalid processing response.") from None

            state = str(payload.get("state", "")).lower()
            if state != last_state:
                logger.info("Video Indexer state changed. video_id=%s state=%s", video_id, state or "unknown")
                last_state = state
            if state == "processed":
                return payload
            if state in {"failed", "quarantined"}:
                failure = payload.get("failureMessage") or payload.get("failureCode") or "processing failed"
                logger.error("Video Indexer processing failed. video_id=%s reason=%s", video_id, str(failure)[:300])
                raise VideoIndexerError(f"Video Indexer processing failed: {str(failure)[:300]}")
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
        raise TimeoutError(f"Video Indexer did not finish within {timeout_seconds} seconds.")

    @staticmethod
    def _instances(insight: dict) -> list[dict]:
        instances = insight.get("instances") or []
        if not instances and ("start" in insight or "end" in insight):
            return [insight]
        return instances

    
    def extract_data(self, vi_json: dict) -> dict:
        """Extract raw and normalized transcript/OCR evidence."""

        import re

        if not isinstance(vi_json, dict):
            raise TypeError("Video Indexer response must be a dictionary.")

        transcript_segments = []
        ocr_segments = []

        def normalize_text(value: str) -> str:
            return re.sub(r"\s+", " ", str(value or "")).strip()

        def is_timestamp_only(value: str) -> bool:
            # Matches values such as 00:01, 01:25 and 0:01:25
            return bool(
                re.fullmatch(
                    r"\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?",
                    value
                )
            )

        for video in vi_json.get("videos") or []:
            insights = video.get("insights") or {}

            # Transcript extraction
            for item in insights.get("transcript") or []:
                text = normalize_text(item.get("text"))

                if not text:
                    continue

                for instance in self._instances(item):
                    transcript_segments.append({
                        "text": text,
                        "start": instance.get("start"),
                        "end": instance.get("end"),
                        "confidence": instance.get("confidence"),
                        "language": item.get("language"),
                    })

        # OCR extraction
        for item in insights.get("ocr") or []:
            text = normalize_text(item.get("text"))

            if not text:
                continue

            for instance in self._instances(item):
                ocr_segments.append({
                    "text": text,
                    "start": instance.get("start"),
                    "end": instance.get("end"),
                    "confidence": instance.get("confidence"),
                })

        # Preserve raw OCR observations for auditability.
        raw_ocr_segments = [dict(item) for item in ocr_segments]

        # Filter obvious timestamp-only noise.
        filtered_ocr_segments = [
            item for item in ocr_segments
            if not is_timestamp_only(item["text"])
    ]

        # Deduplicate identical text observations while retaining
        # their individual timestamps.
        seen = set()
        cleaned_ocr_segments = []

        for item in filtered_ocr_segments:
            key = (
                item["text"].casefold(),
                item.get("start"),
                item.get("end"),
            )

            if key in seen:
                continue

            seen.add(key)
            cleaned_ocr_segments.append(item)

        summary = vi_json.get("summarizedInsights") or {}
        duration_info = summary.get("duration") or {}

        duration = (
            duration_info.get("seconds")
            if isinstance(duration_info, dict)
            else None
        )

        return {
            "transcript": " ".join(
                item["text"] for item in transcript_segments
            ),
            "transcript_segments": transcript_segments,

            # Preserve the original OCR observations.
            "raw_ocr_segments": raw_ocr_segments,

            # Cleaned OCR evidence.
            "ocr_text": "\n".join(
                item["text"] for item in cleaned_ocr_segments
            ),
            "ocr_segments": cleaned_ocr_segments,

        "video_metadata": {
            "video_id": vi_json.get("id"),
            "name": vi_json.get("name"),
            "duration": duration,
            "state": vi_json.get("state"),
            "platform": "youtube",
        },
    }


    def close(self) -> None:
        """Release HTTP and Azure identity resources. Safe to call more than once."""
        if self._closed:
            return
        self._closed = True
        self.session.close()
        close = getattr(self.credential, "close", None)
        if callable(close):
            close()
