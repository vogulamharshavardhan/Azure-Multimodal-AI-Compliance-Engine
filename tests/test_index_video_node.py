
from unittest.mock import MagicMock, patch

from backend.src.graph.nodes import index_video_node
from dotenv import load_dotenv
load_dotenv()

def test_index_video_node_success(tmp_path):
    """Test video indexing without real downloads or Azure uploads."""

    fake_video = tmp_path / "test_video.mp4"
    fake_video.write_bytes(b"mock-video-content")

    fake_extracted_data = {
        "transcript": "This is a sample transcript.",
        "transcript_segments": [
            {
                "text": "This is a sample transcript.",
                "start": 0.0,
                "end": 5.0,
            }
        ],
        "ocr_text": "18+ Terms apply",
        "ocr_segments": [
            {
                "text": "18+ Terms apply",
                "start": 1.0,
                "end": 2.0,
            }
        ],
        "video_metadata": {
            "video_id": "test-video-123",
            "name": "test-video",
            "duration": 10,
            "state": "Processed",
            "platform": "youtube",
        },
    }

    mock_downloader = MagicMock()
    mock_downloader.download_youtube_video.return_value = str(fake_video)

    mock_blob_storage = MagicMock()
    mock_blob_storage.upload_and_create_read_url.return_value = (
        "videos/test/video.mp4", "https://storage.example/video.mp4?sv=redacted"
    )

    mock_video_indexer = MagicMock()
    mock_video_indexer.upload_video_from_url.return_value = "test-video-123"
    mock_video_indexer.wait_for_processing.return_value = {
        "state": "Processed"
    }
    mock_video_indexer.extract_data.return_value = fake_extracted_data

    with (
        patch(
            "backend.src.graph.nodes.YouTubeDownloader",
            return_value=mock_downloader,
        ),
        patch(
            "backend.src.graph.nodes.ensure_h264",
            return_value=str(fake_video),
        ),
        patch(
            "backend.src.graph.nodes.BlobStorageService",
            return_value=mock_blob_storage,
        ),
        patch(
            "backend.src.services.video_indexer.VideoIndexerService",
            return_value=mock_video_indexer,
        ),
    ):
        result = index_video_node(
            {
                "video_url": "https://youtu.be/0CmtDk-joT4",
                "errors": [],
            }
        )

    assert result["indexing_status"] == "COMPLETED"
    assert result["transcript"] == "This is a sample transcript."
    assert result["ocr_text"] == "18+ Terms apply"
    assert result["metadata"]["video_id"] == "test-video-123"

    assert result["transcript_segments"] == fake_extracted_data[
        "transcript_segments"
    ]

    assert result["ocr_segments"] == fake_extracted_data[
        "ocr_segments"
    ]

    assert result["extraction_status"]["download_status"] == "SUCCESS"

    mock_downloader.download_youtube_video.assert_called_once()
    mock_blob_storage.upload_and_create_read_url.assert_called_once()
    mock_video_indexer.upload_video_from_url.assert_called_once()
    mock_blob_storage.delete.assert_called_once_with("videos/test/video.mp4")
    mock_blob_storage.close.assert_called_once()
    mock_video_indexer.wait_for_processing.assert_called_once()
    mock_video_indexer.extract_data.assert_called_once()
    mock_video_indexer.close.assert_called_once()

from unittest.mock import MagicMock, patch

from backend.src.graph.nodes import index_video_node


def test_index_video_node_rejects_invalid_url():
    result = index_video_node(
        {
            "video_url": "https://example.com/video",
            "errors": [],
        }
    )

    assert result["indexing_status"] == "FAILED"
    assert result["final_status"] == "REVIEW_REQUIRED"
    assert result["current_stage"] == "INDEXING_FAILED"


def test_index_video_node_download_failure():
    mock_downloader = MagicMock()
    mock_downloader.download_youtube_video.side_effect = RuntimeError(
        "Simulated download failure"
    )

    with patch(
        "backend.src.graph.nodes.YouTubeDownloader",
        return_value=mock_downloader,
    ):
        result = index_video_node(
            {
                "video_url": "https://youtu.be/0CmtDk-joT4",
                "errors": [],
            }
        )

    assert result["indexing_status"] == "FAILED"
    assert result["final_status"] == "REVIEW_REQUIRED"
    assert result["current_stage"] == "INDEXING_FAILED"


def test_index_video_node_azure_upload_failure(tmp_path):
    fake_video = tmp_path / "test_video.mp4"
    fake_video.write_bytes(b"mock-video-content")

    mock_downloader = MagicMock()
    mock_downloader.download_youtube_video.return_value = str(fake_video)

    mock_blob_storage = MagicMock()
    mock_blob_storage.upload_and_create_read_url.return_value = (
        "videos/test/video.mp4", "https://storage.example/video.mp4?sv=redacted"
    )

    mock_video_indexer = MagicMock()
    mock_video_indexer.upload_video_from_url.side_effect = RuntimeError(
        "Simulated Azure Video Indexer URL-ingestion failure"
    )

    with (
        patch(
            "backend.src.graph.nodes.YouTubeDownloader",
            return_value=mock_downloader,
        ),
        patch(
            "backend.src.graph.nodes.ensure_h264",
            return_value=str(fake_video),
        ),
        patch(
            "backend.src.graph.nodes.BlobStorageService",
            return_value=mock_blob_storage,
        ),
        patch(
            "backend.src.services.video_indexer.VideoIndexerService",
            return_value=mock_video_indexer,
        ),
    ):
        result = index_video_node(
            {
                "video_url": "https://youtu.be/0CmtDk-joT4",
                "errors": [],
            }
        )

    assert result["indexing_status"] == "FAILED"
    assert result["final_status"] == "REVIEW_REQUIRED"
    assert result["current_stage"] == "INDEXING_FAILED"

    mock_video_indexer.close.assert_called_once()
    mock_blob_storage.delete.assert_called_once_with("videos/test/video.mp4")
    mock_blob_storage.close.assert_called_once()
