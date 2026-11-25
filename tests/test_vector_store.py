from langchain_core.documents import Document

from backend.src.retrieval.vector_store import retrieve_regulatory_evidence


class FakeVectorStore:
    def similarity_search_with_relevance_scores(self, query, k):
        assert query
        assert k == 3
        return [
            (
                Document(
                    page_content="Disclose material connections clearly and conspicuously.",
                    metadata={
                        "source": "ftc-guide.md",
                        "source_url": "https://www.ftc.gov/example",
                        "source_authority": "Federal Trade Commission",
                        "source_checked_date": "2026-11-23",
                        "chunk_id": "chunk-001",
                    },
                ),
                0.82,
            ),
            (Document(page_content="Unrelated low-score passage", metadata={"source": "other.md"}), 0.04),
        ]


def test_retrieval_filters_low_relevance_and_preserves_provenance(monkeypatch):
    monkeypatch.setenv("MIN_POLICY_RELEVANCE_SCORE", "0.15")
    text, citations = retrieve_regulatory_evidence(FakeVectorStore(), "material connection disclosure", k=3)

    assert "Disclose material connections" in text
    assert "Unrelated low-score passage" not in text
    assert len(citations) == 1
    assert citations[0]["source_url"] == "https://www.ftc.gov/example"
    assert citations[0]["source_authority"] == "Federal Trade Commission"
    assert citations[0]["chunk_id"] == "chunk-001"
    assert citations[0]["relevance_score"] == 0.82


def test_retrieval_rejects_invalid_relevance_threshold(monkeypatch):
    import pytest
    from backend.src.core.exceptions import RetrievalError

    monkeypatch.setenv("MIN_POLICY_RELEVANCE_SCORE", "1.5")
    with pytest.raises(RetrievalError):
        retrieve_regulatory_evidence(FakeVectorStore(), "query", k=3)
