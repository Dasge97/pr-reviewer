from __future__ import annotations

import json
from pathlib import Path

import pytest

from service.models import PreparedWorkspace, PullRequestRef, RepoRegistration, ReviewDefaults, WebhookIntake
from service.review_runner import build_review_prompt, load_repo_review_config, load_requirements_markdown, parse_review_output


def test_load_repo_review_config_overrides_defaults(tmp_path: Path):
    defaults = ReviewDefaults(prompt="Default prompt", include_paths=["src"], exclude_paths=["tests"], requirements_file="requerimientos.md")
    (tmp_path / ".pr-reviewer.yml").write_text(
        "prompt: Override\ninclude_paths: [service/]\nexclude_paths: [docs/]\nrequirements_file: docs/requerimientos.md\n",
        encoding="utf-8",
    )

    config = load_repo_review_config(tmp_path, defaults)

    assert config.prompt == "Override"
    assert config.include_paths == ["service/"]
    assert config.exclude_paths == ["docs/"]
    assert config.requirements_file == "docs/requerimientos.md"


def test_load_requirements_markdown_fallbacks(tmp_path: Path):
    (tmp_path / "requirements.md").write_text("# Req\nNo debug logs", encoding="utf-8")

    used_path, content = load_requirements_markdown(tmp_path, "requerimientos.md")

    assert used_path == "requirements.md"
    assert content is not None
    assert "No debug logs" in content


def test_build_review_prompt_includes_requirements():
    repo = RepoRegistration(
        workspace="demo-workspace",
        slug="demo-repo",
        clone_url="https://example.invalid/demo-repo.git",
        human_workspace_root="C:/repos/demo",
        bot_workspace_root="C:/bot/demo",
        webhook_secret_env="BB_SECRET",
        bitbucket_token_env="BB_TOKEN",
    )
    pr = PullRequestRef(
        workspace="demo-workspace",
        repo_slug="demo-repo",
        pr_id=7,
        title="Improve parser",
        source_branch="feature/parser",
        source_commit="abc123",
        target_branch="main",
        target_commit="def456",
    )
    intake = WebhookIntake(event_type="pullrequest:updated", repo=repo, pull_request=pr, raw_payload={})
    workspace = PreparedWorkspace(mirror_dir=Path("/tmp/mirror"), workspace_dir=Path("/tmp/workspace"))
    review_defaults = ReviewDefaults(prompt="Use requirements first.")
    review_config = load_repo_review_config(Path("/tmp/non-existent"), review_defaults)

    prompt = build_review_prompt(
        intake,
        workspace,
        review_config,
        "requerimientos.md",
        "- Every endpoint must validate input",
    )

    assert "Project requirements source: requerimientos.md" in prompt
    assert "Every endpoint must validate input" in prompt
    assert "Apply these requirements as highest priority" in prompt


def test_parse_review_output_requires_fields():
    with pytest.raises(ValueError):
        parse_review_output('{"status": "approved"}')


def test_parse_review_output_accepts_structured_json():
    result = parse_review_output(
        '{"status": "approved", "summary": "Looks good.", "review_body": "Ship it.", "findings": []}'
    )

    assert result.status == "approved"
    assert result.summary == "Looks good."
    assert result.review_body == "Ship it."
    assert result.findings == []


def test_parse_review_output_applies_length_limits():
    long_summary = "S" * 400
    long_body = "B" * 2000
    findings = ["F" * 300 for _ in range(10)]
    payload = {
        "status": "changes_requested",
        "summary": long_summary,
        "review_body": long_body,
        "findings": findings,
    }

    result = parse_review_output(json.dumps(payload))

    assert len(result.summary) <= 280
    assert len(result.review_body) <= 1200
    assert len(result.findings) == 5
    assert all(len(item) <= 160 for item in result.findings)
