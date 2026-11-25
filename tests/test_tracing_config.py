from backend.src.api.tracing import setup_langsmith_tracing
from dotenv import load_dotenv
load_dotenv()

def test_langsmith_tracing_normalizes_legacy_environment(monkeypatch):
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    # Isolate the legacy fallback from values loaded from the developer's .env.
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGCHAIN_API_KEY", "test-key")
    monkeypatch.setenv("LANGCHAIN_PROJECT", "test-project")

    assert setup_langsmith_tracing() is True
    assert __import__("os").environ["LANGSMITH_TRACING"] == "true"
    assert __import__("os").environ["LANGSMITH_API_KEY"] == "test-key"
    assert __import__("os").environ["LANGSMITH_PROJECT"] == "test-project"


def test_langsmith_tracing_requires_explicit_enable_and_key(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    assert setup_langsmith_tracing() is False



def test_langsmith_tracing_prefers_current_project_when_both_are_set(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "current-key")
    monkeypatch.setenv("LANGSMITH_PROJECT", "current-project")
    monkeypatch.setenv("LANGCHAIN_PROJECT", "legacy-project")

    assert setup_langsmith_tracing() is True
    assert __import__("os").environ["LANGSMITH_PROJECT"] == "current-project"
    assert __import__("os").environ["LANGCHAIN_PROJECT"] == "current-project"
