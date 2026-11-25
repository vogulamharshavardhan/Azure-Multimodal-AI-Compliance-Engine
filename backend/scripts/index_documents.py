"""Index approved PDF and Markdown policy sources into Azure AI Search."""

from __future__ import annotations

import hashlib
import logging
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
load_dotenv()
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
ENV_FILE = PROJECT_ROOT / ".env"

# Load the project .env before importing/calling the shared client factories.
load_dotenv(ENV_FILE, override=False)

from backend.src.core.logging_config import setup_logging
from backend.src.core.exceptions import DocumentIndexingError

setup_logging()
logger = logging.getLogger("compliance.indexer")


def discover_policy_files() -> list[Path]:
    """Find supported PDF and Markdown policy sources under backend/data."""
    if not DATA_DIR.is_dir():
        raise DocumentIndexingError(f"PDF data directory does not exist: {DATA_DIR}")

    pdfs = sorted(
        path
        for path in DATA_DIR.rglob("*")
        if path.is_file() and path.suffix.lower() in {".pdf", ".md"}
    )
    if not pdfs:
        raise DocumentIndexingError(f"No supported policy files found under {DATA_DIR}")

    logger.info("Discovered %d policy file(s).", len(pdfs))
    for policy_path in pdfs:
        logger.info("Discovered policy file: %s", policy_path.relative_to(DATA_DIR).as_posix())
    return pdfs


def create_splitter() -> RecursiveCharacterTextSplitter:
    """Split extracted PDF text into overlapping chunks."""
    return RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        add_start_index=True,
        length_function=len,
    )


def stable_chunk_id(
    source: str,
    page: Any,
    start_index: Any,
    content: str,
) -> str:
    """Return a deterministic key for an unchanged document chunk."""
    identity = f"{source}|{page}|{start_index}|{content}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def process_policy_files(
    policy_paths: list[Path],
    splitter: RecursiveCharacterTextSplitter,
) -> tuple[list[Document], list[str]]:
    """Load and split policy sources, retaining source and page metadata.

    PyPDFLoader reports zero-based page numbers. We preserve that metadata in
    Azure AI Search; the retrieval/audit layer can convert it to one-based
    page numbers when displaying citations.
    """
    all_chunks: list[Document] = []
    failed_files: list[str] = []

    for policy_path in policy_paths:
        relative_source = policy_path.relative_to(DATA_DIR).as_posix()

        try:
            logger.info("Extracting text from %s", relative_source)
            if policy_path.suffix.lower() == ".pdf":
                pages = PyPDFLoader(str(policy_path)).load()
                if not pages:
                    raise ValueError("PDF loader returned no pages.")
                pages_with_text = [
                    page for page in pages if page.page_content and page.page_content.strip()
                ]
                if not pages_with_text:
                    raise ValueError("No extractable text found in PDF; OCR is required.")
            else:
                pages_with_text = TextLoader(
                    str(policy_path), encoding="utf-8"
                ).load()

            for page in pages_with_text:
                page.metadata.update({
                    "source": relative_source,
                    "document_type": "policy_reference",
                    "source_authority": (
                        "Federal Trade Commission"
                        if relative_source.startswith(("ftc-", "1001a-influencer-guide"))
                        else "Google Ads Help"
                        if relative_source.startswith("google-ads-")
                        else "Unverified local source"
                    ),
                    "source_url": (
                        "https://www.ftc.gov/business-guidance/resources/ftcs-endorsement-guides-what-people-are-asking"
                        if relative_source.startswith("ftc-")
                        else "https://www.ftc.gov/business-guidance/resources/disclosures-101-social-media-influencers"
                        if relative_source.startswith("1001a-influencer-guide")
                        else "https://support.google.com/google-ads/answer/13547298"
                        if relative_source.startswith("google-ads-")
                        else ""
                    ),
                    "source_checked_date": (
                        "2026-11-23"
                        if relative_source.endswith(".md")
                        else "2019-11" if relative_source.startswith("1001a-influencer-guide")
                        else ""
                    ),
                })

            file_chunks = [
                chunk
                for chunk in splitter.split_documents(pages_with_text)
                if chunk.page_content and chunk.page_content.strip()
            ]

            if not file_chunks:
                raise ValueError("No text chunks were generated.")

            for chunk in file_chunks:
                chunk.metadata["chunk_id"] = stable_chunk_id(
                    source=relative_source,
                    page=chunk.metadata.get("page"),
                    start_index=chunk.metadata.get("start_index"),
                    content=chunk.page_content,
                )

            all_chunks.extend(file_chunks)
            logger.info(
                "Generated %d chunk(s) from %s.",
                len(file_chunks),
                relative_source,
            )

        except Exception:
            logger.exception("Failed to process policy source: %s", relative_source)
            failed_files.append(relative_source)

    return all_chunks, failed_files


def remove_deprecated_source_chunks(
    deprecated_sources: set[str] | None = None,
    batch_size: int = 500,
) -> int:
    """Delete only explicitly retired source-file chunks from Azure AI Search."""
    import json
    import os

    retired = deprecated_sources or {"youtube-ad-specs.pdf"}
    if batch_size < 1:
        raise ValueError("batch_size must be greater than zero.")

    client = SearchClient(
        endpoint=os.getenv("AZURE_SEARCH_ENDPOINT", "").strip(),
        index_name=os.getenv("AZURE_SEARCH_INDEX_NAME", "").strip(),
        credential=AzureKeyCredential(os.getenv("AZURE_SEARCH_API_KEY", "").strip()),
    )
    try:
        ids: list[str] = []
        for item in client.search(search_text="*", select=["id", "metadata"]):
            metadata = item.get("metadata") or {}
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except json.JSONDecodeError:
                    metadata = {}
            source = metadata.get("source") if isinstance(metadata, dict) else None
            if source in retired and item.get("id"):
                ids.append(str(item["id"]))

        deleted = 0
        for offset in range(0, len(ids), batch_size):
            batch = [{"id": identifier} for identifier in ids[offset:offset + batch_size]]
            results = client.delete_documents(documents=batch)
            failed = [result for result in results if not getattr(result, "succeeded", False)]
            if failed:
                raise DocumentIndexingError(
                    f"Azure AI Search failed to delete {len(failed)} retired policy chunk(s)."
                )
            deleted += len(batch)
        logger.info("Removed %d chunk(s) from retired policy sources.", deleted)
        return deleted
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def upload_chunks(
    vector_store: Any,
    chunks: list[Document],
    batch_size: int = 100,
) -> int:
    """Upload document chunks in bounded batches with deterministic IDs."""
    if batch_size < 1:
        raise ValueError("batch_size must be greater than zero.")

    uploaded_count = 0

    for offset in range(0, len(chunks), batch_size):
        batch = chunks[offset : offset + batch_size]
        ids = [chunk.metadata["chunk_id"] for chunk in batch]

        logger.info(
            "Uploading batch %d containing %d chunk(s).",
            (offset // batch_size) + 1,
            len(batch),
        )

        # Passing deterministic IDs makes rerunning the script idempotent for
        # unchanged chunks: the same Azure AI Search keys are overwritten.
        vector_store.add_documents(documents=batch, ids=ids)
        uploaded_count += len(batch)

        logger.info(
            "Successfully submitted %d of %d chunk(s).",
            uploaded_count,
            len(chunks),
        )

    return uploaded_count


def index_documents() -> bool:
    """Run policy-source ingestion and upload all successfully processed chunks."""
    logger.info("Starting regulatory document indexing.")
    logger.info("Project root: %s", PROJECT_ROOT)
    logger.info("Policy source directory: %s", DATA_DIR)

    try:
        # Import here so .env has already been loaded and this script uses the
        # exact same client configuration as the graph's retrieval node.
        from backend.src.retrieval.embeddings import get_embedding_client
        from backend.src.retrieval.vector_store import get_vector_store

        policy_paths = discover_policy_files()
        splitter = create_splitter()
        chunks, failed_files = process_policy_files(policy_paths, splitter)

        if not chunks:
            logger.error("No chunks were generated. Nothing was uploaded.")
            return False

        logger.info("Prepared %d total chunk(s).", len(chunks))

        # Validate the embedding endpoint before attempting Search uploads.
        embeddings = get_embedding_client()
        test_vector = embeddings.embed_query("compliance indexing connectivity check")
        if not test_vector:
            raise DocumentIndexingError(
                "Embedding service returned an empty vector."
            )

        logger.info(
            "Embedding service validated. Vector dimensions: %d",
            len(test_vector),
        )

        # get_vector_store() owns Search endpoint, key, index name, and
        # embedding configuration. Its AzureSearch constructor is responsible
        # for connecting to/initializing the configured index.
        #vector_store = get_vector_store()
        vector_store = get_vector_store(embeddings)
        remove_deprecated_source_chunks()
        uploaded_count = upload_chunks(vector_store, chunks)

        logger.info(
            "Indexing summary: policy files discovered=%d, chunks uploaded=%d, "
            "policy files failed=%d",
            len(policy_paths),
            uploaded_count,
            len(failed_files),
        )

        if failed_files:
            logger.error(
                "Indexing completed with policy-source processing failures: %s",
                ", ".join(failed_files),
            )
            return False

        logger.info("Regulatory document indexing completed successfully.")
        return True

    except Exception:
        logger.exception("Regulatory document indexing failed.")
        return False


if __name__ == "__main__":
    sys.exit(0 if index_documents() else 1)
