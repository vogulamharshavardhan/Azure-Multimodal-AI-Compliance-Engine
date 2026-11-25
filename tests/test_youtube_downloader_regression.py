from pathlib import Path

from backend.src.services import youtube_downloader as downloader_module
from backend.src.services.youtube_downloader import YouTubeDownloader


def test_single_video_download_does_not_use_max_downloads(monkeypatch, tmp_path):
    captured = {}

    class FakeYoutubeDL:
        def __init__(self, options):
            captured.update(options)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download):
            assert download is True
            output = Path(captured["outtmpl"].replace(".%(ext)s", ".mp4"))
            output.write_bytes(b"video-bytes")
            return {"id": "test-video", "ext": "mp4", "format_id": "test"}

        def prepare_filename(self, info):
            return captured["outtmpl"].replace(".%(ext)s", ".mp4")

    monkeypatch.setattr(downloader_module.yt_dlp, "YoutubeDL", FakeYoutubeDL)

    result = YouTubeDownloader().download_youtube_video(
        "https://youtu.be/abcdefghijk", output_dir=tmp_path
    )

    assert Path(result).read_bytes() == b"video-bytes"
    assert captured["noplaylist"] is True
    assert "max_downloads" not in captured
