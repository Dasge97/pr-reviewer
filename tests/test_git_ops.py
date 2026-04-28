from __future__ import annotations

import subprocess
from pathlib import Path

from service.git_ops import prepare_pr_workspace
from service.models import PullRequestRef, WebhookIntake


def _git(args: list[str], cwd: Path | None = None):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_prepare_pr_workspace_resets_existing_checkout(runtime_env):
    from service.config import load_repo_config, load_settings, repo_index

    source_repo = Path(runtime_env["data_dir"]).parent / "source"
    source_repo.mkdir(parents=True)
    _git(["init", "-b", "main"], source_repo)
    _git(["config", "user.email", "test@example.com"], source_repo)
    _git(["config", "user.name", "Tester"], source_repo)
    (source_repo / "file.txt").write_text("one\n", encoding="utf-8")
    _git(["add", "file.txt"], source_repo)
    _git(["commit", "-m", "init"], source_repo)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=source_repo, check=True, capture_output=True, text=True).stdout.strip()

    settings = load_settings()
    repo = repo_index(load_repo_config(settings.repos_config_path))["demo-workspace/demo-repo"]
    repo.clone_url = str(source_repo)
    intake = WebhookIntake(
        event_type="pullrequest:updated",
        repo=repo,
        pull_request=PullRequestRef(
            workspace=repo.workspace,
            repo_slug=repo.slug,
            pr_id=7,
            title="test",
            source_branch="main",
            source_commit=commit,
            target_branch="main",
            target_commit=commit,
        ),
        raw_payload={},
    )

    first = prepare_pr_workspace(intake)
    (first.workspace_dir / "scratch.txt").write_text("dirty\n", encoding="utf-8")
    second = prepare_pr_workspace(intake)

    assert second.workspace_dir.exists()
    assert not (second.workspace_dir / "scratch.txt").exists()
