from __future__ import annotations

import json

import httpx
import pytest

from service.bitbucket import BitbucketClient, build_comment_body, build_comment_marker
from service.models import ReviewDefaults, ReviewResult


def test_build_comment_marker_and_body():
    result = ReviewResult(
        status="approved",
        summary="Looks good.",
        review_body="No blocking issues found.",
        findings=[],
    )
    body = build_comment_body("demo-workspace", 42, result)
    assert build_comment_marker("demo-workspace", 42) in body
    assert "Looks good." in body


def test_upsert_comment_uses_create_then_update(runtime_env, monkeypatch):
    from service.config import load_repo_config, load_settings

    repo = load_repo_config(load_settings().repos_config_path).repos[0]
    calls = []

    class FakeResponse:
        def __init__(self, comment_id: int):
            self._comment_id = comment_id

        def raise_for_status(self):
            return None

        def json(self):
            return {"id": self._comment_id}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers, json):
            calls.append(("post", url, json))
            return FakeResponse(100)

        def put(self, url, headers, json):
            calls.append(("put", url, json))
            return FakeResponse(100)

    monkeypatch.setattr(httpx, "Client", FakeClient)
    client = BitbucketClient(repo)
    result = ReviewResult(status="comment", summary="Summary", review_body="Body", findings=["a"])

    first = client.upsert_comment(42, result)
    second = client.upsert_comment(42, result, existing_comment_id=first)

    assert first == "100"
    assert second == "100"
    assert calls[0][0] == "post"
    assert calls[1][0] == "put"
