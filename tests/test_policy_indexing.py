from types import SimpleNamespace

from backend.scripts import index_documents


def test_retired_policy_cleanup_deletes_only_explicit_source(monkeypatch):
    deleted = []

    class FakeSearchClient:
        def __init__(self, **kwargs):
            self.closed = False

        def search(self, search_text, select):
            return [
                {"id": "old-1", "metadata": '{"source":"youtube-ad-specs.pdf"}'},
                {"id": "current-1", "metadata": '{"source":"google-ads-youtube-video-specs.md"}'},
                {"id": "other-1", "metadata": '{"source":"ftc-guide.pdf"}'},
            ]

        def delete_documents(self, documents):
            deleted.extend(documents)
            return [SimpleNamespace(succeeded=True) for _ in documents]

        def close(self):
            self.closed = True

    monkeypatch.setenv("AZURE_SEARCH_ENDPOINT", "https://search.example")
    monkeypatch.setenv("AZURE_SEARCH_INDEX_NAME", "brand-guardian")
    monkeypatch.setenv("AZURE_SEARCH_API_KEY", "test-key")
    monkeypatch.setattr(index_documents, "SearchClient", FakeSearchClient)

    count = index_documents.remove_deprecated_source_chunks()

    assert count == 1
    assert deleted == [{"id": "old-1"}]
