"""Shared test configuration. Unit tests never start external telemetry."""
import os

os.environ["APP_ENV"] = "test"
os.environ["API_KEY"] = "test-only-secret-key-with-at-least-32-characters"
os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"] = ""
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
