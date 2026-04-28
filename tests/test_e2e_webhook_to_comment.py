from __future__ import annotations

import json
import logging
import time

from fastapi.testclient import TestClient


def test_e2e_webhook_to_comment_and_duplicate_suppression(runtime_env, webhook_payload, signature, monkeypatch):
    from service.app import create_app
    from service.models import PreparedWorkspace, ReviewResult

    comments = []

    monkeypatch.setattr(
        "service.app.prepare_pr_workspace",
        lambda intake: PreparedWorkspace(
            mirror_dir=runtime_env["bot_root"] / "repos" / "demo-repo.git",
            workspace_dir=runtime_env["bot_root"] / "workspaces" / "demo-repo" / "pr-42",
            metadata={},
        ),
    )
    monkeypatch.setattr(
        "service.app.run_review",
        lambda intake, workspace: ReviewResult(
            status="changes_requested",
            summary="Found an issue.",
            review_body="Please add a regression test.",
            findings=["Regression coverage missing"],
        ),
    )

    class FakeBitbucketClient:
        def __init__(self, repo):
            self.repo = repo

        def upsert_comment(self, pr_id, result, existing_comment_id=None):
            comments.append({"pr_id": pr_id, "existing_comment_id": existing_comment_id, "status": result.status})
            return "555"

    monkeypatch.setattr("service.app.BitbucketClient", FakeBitbucketClient)

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
        deadline = time.time() + 3
        runtime = client.app.state.runtime
        while time.time() < deadline:
            jobs = runtime.state.list_jobs()
            if jobs and jobs[0]["status"] == "completed":
                break
            time.sleep(0.05)

        jobs = runtime.state.list_jobs()

    assert first.json()["status"] == "accepted"
    assert second.json()["status"] == "duplicate"
    assert jobs[0]["status"] == "completed"
    assert len(comments) == 1


def test_failed_job_is_retriable_and_logged(runtime_env, webhook_payload, signature, monkeypatch, caplog):
    from service.app import create_app

    monkeypatch.setattr("service.app.prepare_pr_workspace", lambda intake: (_ for _ in ()).throw(RuntimeError("git fetch failed")))

    with caplog.at_level(logging.INFO, logger="pr_revisor"):
        with TestClient(create_app()) as client:
            response = client.post(
                "/webhooks/bitbucket",
                content=json.dumps(webhook_payload),
                headers={"X-Event-Key": "pullrequest:updated", "X-Hub-Signature": signature, "Content-Type": "application/json"},
            )
            deadline = time.time() + 3
            runtime = client.app.state.runtime
            while time.time() < deadline:
                jobs = runtime.state.list_jobs()
                if jobs and jobs[0]["status"] == "failed":
                    break
                time.sleep(0.05)

            jobs = runtime.state.list_jobs()

    assert response.status_code == 200
    assert jobs[0]["status"] == "failed"
    assert jobs[0]["retriable"] == 1
    assert jobs[0]["error_stage"] == "workspace_preparation"
    assert "job.failed stage=workspace_preparation retriable=True" in caplog.text
