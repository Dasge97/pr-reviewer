from __future__ import annotations

from pathlib import Path

from service.config import load_repo_config, load_settings, repo_index
from service.state import StateStore
from service.webhooks import WebhookIntake


def test_state_registers_and_claims_job(runtime_env, webhook_payload):
    from service.models import PullRequestRef

    settings = load_settings()
    repo = repo_index(load_repo_config(settings.repos_config_path))["demo-workspace/demo-repo"]
    pr = PullRequestRef(
        workspace="demo-workspace",
        repo_slug="demo-repo",
        pr_id=42,
        title="Improve webhook parser",
        source_branch="feature/parser",
        source_commit="abc123source",
        target_branch="main",
        target_commit="def456target",
    )
    intake = WebhookIntake(event_type="pullrequest:updated", repo=repo, pull_request=pr, raw_payload=webhook_payload)
    state = StateStore(settings.db_path)
    state.init_schema()

    admitted, job_id = state.register_webhook_event(intake)
    job = state.claim_next_job()

    assert admitted is True
    assert job_id is not None
    assert job is not None
    assert job.pr_key == intake.pr_key
