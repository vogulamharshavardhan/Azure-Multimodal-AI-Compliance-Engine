
"""YouTube video downloading service for Brand Guardian."""

from __future__ import annotations

import logging
import os
import tempfile
import time
import traceback
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp

from backend.src.core.exceptions import YouTubeDownloadError

logger = logging.getLogger(__name__)


class YouTubeDownloader:
    """Download and validate YouTube videos independently of Azure."""

    ALLOWED_YOUTUBE_HOSTS = {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
        "www.youtu.be",
    }

    @classmethod
    def validate_url(cls, url: str) -> None:
        """Validate supported HTTPS YouTube URLs."""

        try:
            parsed = urlparse(url)
        except (TypeError, ValueError):
            raise ValueError("A valid YouTube URL is required.") from None

        hostname = (parsed.hostname or "").lower()

        if (
            parsed.scheme != "https"
            or hostname not in cls.ALLOWED_YOUTUBE_HOSTS
        ):
            raise ValueError(
                "Only HTTPS URLs from supported YouTube hosts are accepted."
            )

        if parsed.username or parsed.password:
            raise ValueError(
                "YouTube URLs must not contain embedded credentials."
            )

        if hostname in {"youtu.be", "www.youtu.be"}:
            if not parsed.path.strip("/"):
                raise ValueError(
                    "The YouTube short URL is missing its video identifier."
                )

        if "youtube.com" in hostname:
            valid_path = (
                parsed.path == "/watch"
                or parsed.path == "/live"
                or parsed.path.startswith(("/shorts/", "/embed/"))
            )

            if not valid_path:
                raise ValueError(
                    "The supplied YouTube URL does not identify a supported video."
                )

    @staticmethod
    def _positive_limit(name: str, default: int) -> int:
        # Keep the documented conservative resolution ceiling at 1920 px
        # even when older callers still pass the former 1080 px fallback.
        fallback = max(default, 1920) if name == "MAX_VIDEO_DIMENSION" else default
        raw = os.getenv(name, str(fallback)).strip()
        try:
            value = int(raw)
        except ValueError:
            raise YouTubeDownloadError(f"{name} must be a positive integer.") from None
        if value <= 0:
            raise YouTubeDownloadError(f"{name} must be a positive integer.")
        return value

    def download_youtube_video(
        self,
        url: str,
        output_dir: str | Path | None = None,
    ) -> str:
        """Download one YouTube video and return its local filesystem path."""

        self.validate_url(url)

        # Preserve downloaded files during development.
        destination = (
            Path(output_dir).expanduser().resolve()
            if output_dir
            else Path(tempfile.gettempdir()) / "brand_guardian"
        )

        destination.mkdir(parents=True, exist_ok=True)

        unique_name = f"video_{int(time.time())}_{os.getpid()}"

        max_size_mb = self._positive_limit("MAX_VIDEO_SIZE_MB", 250)
        max_duration_seconds = self._positive_limit("MAX_VIDEO_DURATION_SECONDS", 1200)
        max_dimension = self._positive_limit("MAX_VIDEO_DIMENSION", 1920)

        def reject_oversized_or_long_video(info: dict, *, incomplete: bool = False):
            duration = info.get("duration")
            if duration is not None and float(duration) > max_duration_seconds:
                return f"Video duration exceeds the {max_duration_seconds}-second limit."
            size = info.get("filesize") or info.get("filesize_approx")
            if size is not None and int(size) > max_size_mb * 1024 * 1024:
                return f"Video exceeds the {max_size_mb} MB download limit."
            width = info.get("width")
            height = info.get("height")
            if any(value is not None and int(value) > max_dimension for value in (width, height)):
                return f"Video dimensions exceed the {max_dimension}-pixel side limit."
            return None

        options = {
            "format": (
                f"bestvideo[height<={max_dimension}][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]"
                f"/best[height<={max_dimension}][ext=mp4][vcodec^=avc1]"
                f"/best[height<={max_dimension}][ext=mp4]"
                f"/best[height<={max_dimension}]"
            ),
            "max_filesize": max_size_mb * 1024 * 1024,
            "match_filter": reject_oversized_or_long_video,
            "outtmpl": str(destination / f"{unique_name}.%(ext)s"),
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
                    raise YouTubeDownloadError(
                        "YouTube did not return video information."
                    )

                # Log the actual selected format after extraction.
                logger.info(
                    "Selected YouTube format. "
                    "format_id=%s extension=%s video_codec=%s "
                    "audio_codec=%s resolution=%s",
                    info.get("format_id"),
                    info.get("ext"),
                    info.get("vcodec"),
                    info.get("acodec"),
                    info.get("resolution"),
                )

                candidate = Path(downloader.prepare_filename(info))

                if (
                    not candidate.exists()
                    and candidate.with_suffix(".mp4").exists()
                ):
                    candidate = candidate.with_suffix(".mp4")

                if not candidate.exists():
                    matches = list(destination.glob(f"{unique_name}.*"))

                    if not matches:
                        raise YouTubeDownloadError(
                            "Downloaded video file could not be located."
                        )

                    candidate = matches[0]

                if not candidate.is_file() or candidate.stat().st_size <= 0:
                    raise YouTubeDownloadError("Downloaded video file is empty or invalid.")
                if candidate.stat().st_size > max_size_mb * 1024 * 1024:
                    candidate.unlink(missing_ok=True)
                    raise YouTubeDownloadError(
                        f"Video exceeds the configured {max_size_mb} MB download limit."
                    )

            logger.info(
                "Download completed. file=%s size_mb=%.2f",
                candidate.name,
                candidate.stat().st_size / 1048576,
            )

            return str(candidate)

        except Exception as exc:
            # Remove partial downloads from this request. The generated name
            # is unique to this process and is constrained to the destination.
            for partial in destination.glob(f"{unique_name}.*"):
                try:
                    if partial.is_file():
                        partial.unlink()
                except OSError:
                    logger.exception("Could not remove partial video download.")

            # yt-dlp errors may contain signed media URLs. Log stack frames and
            # exception type, but deliberately omit the exception message.
            logger.error(
                "YouTube download failed. exception_type=%s stack=%s",
                type(exc).__name__,
                "".join(traceback.format_tb(exc.__traceback__)),
            )

            if isinstance(exc, YouTubeDownloadError):
                raise

            raise YouTubeDownloadError(
                "Unable to download the supplied YouTube video."
            ) from None
