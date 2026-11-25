"""Backward-compatible import path for Azure Video Indexer."""

import logging
from dotenv import load_dotenv
load_dotenv()
from backend.src.core.exceptions import VideoIndexerError
from backend.src.ingestion.video_indexer import VideoIndexerService

logger = logging.getLogger(__name__)

__all__ = ["VideoIndexerError", "VideoIndexerService"]
