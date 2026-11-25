"""Shared test setup.

The tests are hermetic: no .env file is read, no credential is requested and
no network call is made. Everything that would reach Azure is replaced with a
fake before the module under test is imported.
"""
import os
import sys
from pathlib import Path

import dotenv
import pytest

# Never load a developer's .env during tests.
dotenv.load_dotenv = lambda *args, **kwargs: False

# A placeholder endpoint with a trailing slash, so URL building is exercised.
os.environ["CONTENT_SAFETY_ENDPOINT"] = "https://example.invalid/"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import content_safety_tools as tools  # noqa: E402


class FakeResponse:
    """Stand-in for requests.Response."""

    def __init__(self, payload=None, error=None):
        self._payload = payload or {}
        self._error = error

    def raise_for_status(self):
        if self._error:
            raise self._error

    def json(self):
        return self._payload


class FakePost:
    """Records every requests.post call and replays queued responses."""

    def __init__(self):
        self.calls = []
        self.responses = []

    def queue(self, payload=None, error=None):
        self.responses.append(FakeResponse(payload, error))

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        if not self.responses:
            raise AssertionError(f"Unexpected HTTP call to {url}")
        return self.responses.pop(0)


@pytest.fixture
def post(monkeypatch):
    """Replace requests.post and the token lookup used by the REST tools."""
    fake = FakePost()
    monkeypatch.setattr(tools.requests, "post", fake)
    monkeypatch.setattr(tools, "_get_bearer_token", lambda: "test-token")
    return fake
