import pytest

from backend.src.core.exceptions import YouTubeDownloadError
from backend.src.services.youtube_downloader import YouTubeDownloader


def test_download_limits_have_conservative_defaults(monkeypatch):
    monkeypatch.delenv("MAX_VIDEO_SIZE_MB", raising=False)
    monkeypatch.delenv("MAX_VIDEO_DURATION_SECONDS", raising=False)
    monkeypatch.delenv("MAX_VIDEO_DIMENSION", raising=False)
    assert YouTubeDownloader._positive_limit("MAX_VIDEO_SIZE_MB", 250) == 250
    assert YouTubeDownloader._positive_limit("MAX_VIDEO_DURATION_SECONDS", 1200) == 1200
    assert YouTubeDownloader._positive_limit("MAX_VIDEO_DIMENSION", 1080) == 1920


@pytest.mark.parametrize("value", ["0", "-1", "not-an-integer"])
def test_download_limits_reject_invalid_values(monkeypatch, value):
    monkeypatch.setenv("MAX_VIDEO_SIZE_MB", value)
    with pytest.raises(YouTubeDownloadError):
        YouTubeDownloader._positive_limit("MAX_VIDEO_SIZE_MB", 250)


def test_downloader_rejects_non_youtube_and_non_https_urls():
    with pytest.raises(ValueError):
        YouTubeDownloader.validate_url("http://www.youtube.com/watch?v=abc")
    with pytest.raises(ValueError):
        YouTubeDownloader.validate_url("https://example.com/video")
