"""Video codec inspection and H.264 normalization."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from backend.src.core.exceptions import VideoProcessingError

logger = logging.getLogger(__name__)

def _ffprobe_codec(path: str) -> str:
    """Detect video codec using FFprobe."""

    probe = shutil.which("ffprobe")

    if not probe:
        raise RuntimeError(
            "ffprobe is not installed or not available on PATH."
        )

    result = subprocess.run(
        [
            probe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(
            "Unable to inspect the downloaded video stream."
        )

    return result.stdout.strip().lower()


def ensure_h264(input_path: str) -> str:
    try:
        """
        Return an H.264 MP4 suitable for Azure Video Indexer.

        The original downloaded file is never modified or deleted.
        """

        source = Path(input_path).expanduser().resolve()

        # Validate input.
        if not source.is_file():
            raise FileNotFoundError(
                f"Input video does not exist: {source}"
            )

        if source.stat().st_size == 0:
            raise RuntimeError("Input video is empty.")

        # Detect codec.
        codec = _ffprobe_codec(str(source))

        # Fast path for H.264.
        if codec == "h264":

            logger.info(
                "[Indexer] Input video is already H.264. "
                "Skipping transcoding."
            )

            return str(source)

        # Locate FFmpeg.
        ffmpeg = shutil.which("ffmpeg")

        if not ffmpeg:
            raise RuntimeError(
                f"Input codec is {codec}. "
                "FFmpeg is required for H.264 conversion."
            )

        # Validate timeout.
        try:
            timeout_seconds = int(
                os.getenv(
                    "VIDEO_TRANSCODE_TIMEOUT_SECONDS",
                    "10800",
                )
            )

        except ValueError as exc:
            raise ValueError(
                "VIDEO_TRANSCODE_TIMEOUT_SECONDS must be an integer."
            ) from exc

        if timeout_seconds <= 0:
            raise ValueError(
                "VIDEO_TRANSCODE_TIMEOUT_SECONDS must be greater than zero."
            )

        # Generate unique output path.
        output_path = source.with_name(
            f"{source.stem}_h264_{uuid.uuid4().hex[:8]}.mp4"
        )

        preset = os.getenv(
            "VIDEO_TRANSCODE_PRESET",
            "medium",
        )

        crf = os.getenv(
            "VIDEO_TRANSCODE_CRF",
            "22",
        )

        command = [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            crf,
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-f",
            "mp4",
            "-n",
            str(output_path),
        ]

        logger.info(
            "[Indexer] Starting video transcode. "
            "codec=%s timeout_seconds=%d",
            codec,
            timeout_seconds,
        )

        started = time.monotonic()

        try:

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )

            if result.returncode != 0:

                error_details = (
                    result.stderr or ""
                ).strip()[-2000:]

                logger.error(
                    "[Indexer] FFmpeg failed. "
                    "return_code=%d details=%s",
                    result.returncode,
                    error_details,
                )

                raise RuntimeError(
                    "FFmpeg failed to convert the video to H.264. "
                    "Check the FFmpeg error log."
                )

            if not output_path.is_file():
                raise RuntimeError(
                    "FFmpeg completed without producing an output file."
                )

            output_size = output_path.stat().st_size

            if output_size < 1024:
                raise RuntimeError(
                    "FFmpeg produced an invalid or incomplete video file."
                )

            output_codec = _ffprobe_codec(str(output_path))

            if output_codec != "h264":
                raise RuntimeError(
                    f"Expected H.264 output, but detected {output_codec}."
                )

            elapsed = time.monotonic() - started

            logger.info(
                "[Indexer] H.264 conversion successful. "
                "elapsed_seconds=%.1f output_mb=%.2f",
                elapsed,
                output_size / (1024 * 1024),
            )

            return str(output_path)

        except subprocess.TimeoutExpired as exc:

            logger.error(
                "[Indexer] Video transcoding timed out "
                "after %d seconds.",
                timeout_seconds,
            )

            raise TimeoutError(
                "Video transcoding exceeded "
                "VIDEO_TRANSCODE_TIMEOUT_SECONDS."
            ) from exc

        except Exception:

            logger.exception(
                "[Indexer] Video transcoding or output validation failed."
            )

            raise

        finally:

            # Remove incomplete output only.
            if output_path.exists():

                try:

                    valid_output = (
                        output_path.is_file()
                        and output_path.stat().st_size >= 1024
                        and _ffprobe_codec(str(output_path)) == "h264"
                    )

                    if not valid_output:
                        output_path.unlink(missing_ok=True)

                except Exception:
                    output_path.unlink(missing_ok=True)
    except VideoProcessingError:
        raise
    except Exception as exc:
        logger.exception(
            "Video processing failed. error_type=%s",
            type(exc).__name__,
        )
        raise VideoProcessingError(
            "Video probing or H.264 normalization failed."
        ) from exc
