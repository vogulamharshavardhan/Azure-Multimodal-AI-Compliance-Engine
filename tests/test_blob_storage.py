from unittest.mock import MagicMock, patch
import pytest
from dotenv import load_dotenv
load_dotenv()
from backend.src.core.exceptions import ConfigurationError
from backend.src.services.blob_storage import BlobStorageService


def test_blob_storage_requires_connection_string(monkeypatch):
    monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
    with pytest.raises(ConfigurationError):
        BlobStorageService()


def test_upload_creates_read_only_sas_and_returns_blob_name(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "AZURE_STORAGE_CONNECTION_STRING",
        "DefaultEndpointsProtocol=https;AccountName=unitaccount;AccountKey=dummy-key;EndpointSuffix=core.windows.net",
    )
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"test-video-bytes")

    mock_blob = MagicMock()
    mock_blob.url = "https://unitaccount.blob.core.windows.net/brand-guardian-temp/test.mp4"
    mock_container = MagicMock()
    mock_container.get_container_properties.return_value = {"public_access": None}
    mock_container.get_blob_client.return_value = mock_blob
    mock_client = MagicMock()
    mock_client.account_name = "unitaccount"
    mock_client.get_container_client.return_value = mock_container

    with (
        patch("backend.src.services.blob_storage.BlobServiceClient.from_connection_string", return_value=mock_client),
        patch("backend.src.services.blob_storage.generate_blob_sas", return_value="sp=r&sig=not-real" ) as make_sas,
    ):
        storage = BlobStorageService()
        blob_name, url = storage.upload_and_create_read_url(video)

    assert blob_name.startswith("videos/")
    assert url.endswith("?sp=r&sig=not-real")
    mock_blob.upload_blob.assert_called_once()
    assert make_sas.call_args.kwargs["permission"].read is True
    assert make_sas.call_args.kwargs["permission"].write is False
    assert make_sas.call_args.kwargs["protocol"] == "https"
    storage.delete(blob_name)
    mock_container.delete_blob.assert_called_once_with(blob_name, delete_snapshots="include")
    storage.close()


def test_existing_container_is_reused(tmp_path, monkeypatch):
    from azure.core.exceptions import ResourceExistsError

    monkeypatch.setenv(
        "AZURE_STORAGE_CONNECTION_STRING",
        "DefaultEndpointsProtocol=https;AccountName=unitaccount;AccountKey=dummy-key;EndpointSuffix=core.windows.net",
    )
    mock_container = MagicMock()
    mock_container.get_container_properties.return_value = {"public_access": None}
    mock_container.create_container.side_effect = ResourceExistsError("exists")
    mock_client = MagicMock()
    mock_client.account_name = "unitaccount"
    mock_client.get_container_client.return_value = mock_container

    with patch(
        "backend.src.services.blob_storage.BlobServiceClient.from_connection_string",
        return_value=mock_client,
    ):
        service = BlobStorageService()

    mock_container.create_container.assert_called_once()
    service.close()
