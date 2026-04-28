from __future__ import annotations

import hashlib
import hmac
import json

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from service.webhooks import parse_bitbucket_webhook


def test_parse_valid_webhook(runtime_env, webhook_payload, signature):
    app = FastAPI()
    from service.config import load_repo_config, load_settings, repo_index

    repo_lookup = repo_index(load_repo_config(load_settings().repos_config_path))

    async def endpoint(request: Request):
        return await parse_bitbucket_webhook(request, repo_lookup)

    app.post("/hook")(endpoint)
    client = TestClient(app)
    response = client.post(
        "/hook",
        content=json.dumps(webhook_payload),
        headers={"X-Event-Key": "pullrequest:updated", "X-Hub-Signature": signature, "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert response.json()["event_type"] == "pullrequest:updated"


def test_reject_invalid_signature(runtime_env, webhook_payload):
    from service.app import create_app

    with TestClient(create_app()) as client:
        response = client.post(
            "/webhooks/bitbucket",
            json=webhook_payload,
            headers={"X-Event-Key": "pullrequest:updated", "X-Hub-Signature": "sha256=bad"},
        )

    assert response.status_code == 401


def test_reject_unsupported_event(runtime_env, webhook_payload, signature):
    from service.app import create_app

    with TestClient(create_app()) as client:
        response = client.post(
            "/webhooks/bitbucket",
            content=json.dumps(webhook_payload),
            headers={"X-Event-Key": "repo:push", "X-Hub-Signature": signature, "Content-Type": "application/json"},
        )

    assert response.status_code == 400


def test_deduplicate_same_revision(runtime_env, webhook_payload, signature, monkeypatch):
    from service.app import create_app

    monkeypatch.setattr("service.app.prepare_pr_workspace", lambda intake: (_ for _ in ()).throw(RuntimeError("stop")))
    with TestClient(create_app()) as client:
        first = client.post(
            "/webhooks/bitbucket",
            content=json.dumps(webhook_payload),
            headers={"X-Event-Key": "pullrequest:updated", "X-Hub-Signature": signature, "Content-Type": "application/json"},
        )
        second = client.post(
            "/webhooks/bitbucket",
            content=json.dumps(webhook_payload),
            headers={"X-Event-Key": "pullrequest:updated", "X-Hub-Signature": signature, "Content-Type": "application/json"},
        )

    assert first.status_code == 200
    assert first.json()["status"] == "accepted"
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"


def test_accept_new_updated_event_with_same_commits(runtime_env, webhook_payload, webhook_secret, monkeypatch):
    from service.app import create_app

    monkeypatch.setattr("service.app.prepare_pr_workspace", lambda intake: (_ for _ in ()).throw(RuntimeError("stop")))

    first_payload = dict(webhook_payload)
    first_payload["pullrequest"] = dict(webhook_payload["pullrequest"])
    first_payload["pullrequest"]["updated_on"] = "2026-04-27T15:24:50.728170+00:00"

    second_payload = dict(webhook_payload)
    second_payload["pullrequest"] = dict(webhook_payload["pullrequest"])
    second_payload["pullrequest"]["updated_on"] = "2026-04-27T15:30:50.728170+00:00"

    def sign(payload: dict) -> str:
        body = json.dumps(payload).encode("utf-8")
        digest = hmac.new(webhook_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    with TestClient(create_app()) as client:
        first = client.post(
            "/webhooks/bitbucket",
            content=json.dumps(first_payload),
            headers={"X-Event-Key": "pullrequest:updated", "X-Hub-Signature": sign(first_payload), "Content-Type": "application/json"},
        )
        second = client.post(
            "/webhooks/bitbucket",
            content=json.dumps(second_payload),
            headers={"X-Event-Key": "pullrequest:updated", "X-Hub-Signature": sign(second_payload), "Content-Type": "application/json"},
        )

    assert first.status_code == 200
    assert first.json()["status"] == "accepted"
    assert second.status_code == 200
    assert second.json()["status"] == "accepted"
