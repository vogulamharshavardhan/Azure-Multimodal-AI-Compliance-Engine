"""Azure OpenAI embedding client configuration."""

from __future__ import annotations

import logging
import os
from dotenv import load_dotenv
load_dotenv()
from langchain_openai import OpenAIEmbeddings

from backend.src.core.exceptions import ConfigurationError, RetrievalError

logger = logging.getLogger(__name__)


def required_env(name: str) -> str:
    """Return a required environment variable without exposing its value."""

    value = os.getenv(name, "").strip()
    if not value:
        logger.error("Required configuration is missing. variable=%s", name)
        raise ConfigurationError(
            f"Missing required environment variable: {name}"
        )
    return value


def get_embedding_client() -> OpenAIEmbeddings:
    """Initialize the Azure OpenAI embedding client."""

    try:
        endpoint = required_env(
            "AZURE_OPENAI_EMBEDDING_ENDPOINT"
        ).rstrip("/")

        client = OpenAIEmbeddings(
            model=required_env("AZURE_OPENAI_EMBEDDING_DEPLOYMENT"),
            base_url=f"{endpoint}/openai/v1/",
            api_key=required_env("AZURE_OPENAI_EMBEDDING_API_KEY"),
            dimensions=1536,
            timeout=90,
            max_retries=2,
        )

        logger.info("Azure OpenAI embedding client configured.")
        return client

    except ConfigurationError:
        raise
    except Exception as exc:
        logger.exception(
            "Failed to initialize Azure OpenAI embeddings. error_type=%s",
            type(exc).__name__,
        )
        raise RetrievalError(
            "Azure OpenAI embedding client initialization failed."
        ) from exc
