"""Azure AI Search vector-store and policy retrieval operations."""

from __future__ import annotations

import logging
import os
from typing import Any
from dotenv import load_dotenv
load_dotenv()
from langchain_community.vectorstores import AzureSearch
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

from backend.src.core.exceptions import ConfigurationError, RetrievalError
from backend.src.retrieval.embeddings import required_env

logger = logging.getLogger(__name__)


def get_vector_store(embeddings: OpenAIEmbeddings) -> AzureSearch:
    """Initialize the Azure AI Search vector store."""

    try:
        store = AzureSearch(
            azure_search_endpoint=required_env("AZURE_SEARCH_ENDPOINT"),
            azure_search_key=required_env("AZURE_SEARCH_API_KEY"),
            index_name=required_env("AZURE_SEARCH_INDEX_NAME"),
            embedding_function=embeddings.embed_query,
        )
        logger.info("Azure AI Search vector store configured.")
        return store

    except ConfigurationError:
        raise
    except Exception as exc:
        logger.exception(
            "Failed to initialize Azure AI Search. error_type=%s",
            type(exc).__name__,
        )
        raise RetrievalError(
            "Azure AI Search initialization failed."
        ) from exc


def retrieve_regulatory_evidence(
    vector_store: AzureSearch,
    query: str,
    k: int = 5,
    domain: str | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Retrieve policy passages and deduplicated source citations."""

    if not query.strip():
        return "", []

    try:
        try:
            minimum_score = float(os.getenv("MIN_POLICY_RELEVANCE_SCORE", "0.15"))
        except ValueError:
            raise ConfigurationError("MIN_POLICY_RELEVANCE_SCORE must be between 0 and 1.") from None
        if not 0.0 <= minimum_score <= 1.0:
            raise ConfigurationError("MIN_POLICY_RELEVANCE_SCORE must be between 0 and 1.")

        from backend.src.auditing.policy_scope import source_matches_domain
        # Over-fetch then restrict to the known source families. This is a client-side
        # scope guard, not an Azure server-side filter; recall is still bounded.
        scored_documents = vector_store.similarity_search_with_relevance_scores(
            query, k=k * 4 if domain else k,
        )
        documents: list[tuple[Document, float]] = [
            (document, float(score))
            for document, score in scored_documents
            if score is not None and float(score) >= minimum_score
            and (not domain or source_matches_domain((document.metadata or {}).get("source", ""), domain))
        ][:k]

        blocks: list[str] = []
        citations: list[dict[str, Any]] = []
        seen: set[tuple[str, int | None, str | None]] = set()

        for document, relevance_score in documents:
            content = (document.page_content or "").strip()
            if not content:
                continue

            metadata = document.metadata or {}
            source = str(
                metadata.get("source")
                or metadata.get("file_name")
                or "Unknown source"
            )

            raw_page = metadata.get("page")
            try:
                page = int(raw_page) + 1 if raw_page is not None else None
            except (TypeError, ValueError):
                page = None

            chunk_id = str(metadata["chunk_id"]) if metadata.get("chunk_id") else None
            citation_key = (source, page, chunk_id)
            if citation_key not in seen:
                citation = {
                    "source": source,
                    "page": page,
                    "relevance_score": round(relevance_score, 4),
                }
                if chunk_id:
                    citation["chunk_id"] = chunk_id
                for field in ("source_url", "source_authority", "source_checked_date"):
                    value = metadata.get(field)
                    if value:
                        citation[field] = str(value)
                citations.append(citation)
                seen.add(citation_key)

            blocks.append(
                f"Source: {source}\n"
                f"PDF page: {page if page is not None else 'Not applicable'}\n"
                f"Source URL: {metadata.get('source_url') or 'Not recorded'}\n"
                f"Relevance score: {relevance_score:.4f}\n"
                f"Policy text:\n{content}"
            )

        logger.info(
            "Retrieved policy evidence. documents=%d citations=%d",
            len(blocks),
            len(citations),
        )
        return "\n\n---\n\n".join(blocks), citations

    except RetrievalError:
        raise
    except Exception as exc:
        logger.exception(
            "Policy evidence retrieval failed. error_type=%s",
            type(exc).__name__,
        )
        raise RetrievalError(
            "Azure AI Search policy retrieval failed."
        ) from exc
