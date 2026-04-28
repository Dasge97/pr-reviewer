from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path

import pytest


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def webhook_payload() -> dict:
    return json.loads((FIXTURES / "bitbucket_pullrequest_updated.json").read_text(encoding="utf-8"))


@pytest.fixture
def webhook_secret() -> str:
    return "super-secret"


@pytest.fixture
def signature(webhook_payload: dict, webhook_secret: str) -> str:
    body = json.dumps(webhook_payload).encode("utf-8")
    digest = hmac.new(webhook_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest.fixture
def runtime_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, webhook_secret: str):
    data_dir = tmp_path / "data"
    var_dir = tmp_path / "var"
    repos_path = tmp_path / "repos.yaml"
    bot_root = tmp_path / "bot"
    repos_path.write_text(
        f"""
defaults:
  prompt: Review carefully and return JSON only.
  include_paths: []
  exclude_paths: []
  config_path: .pr-reviewer.yml
  opencode_command: [opencode, run]
repos:
  - workspace: demo-workspace
    slug: demo-repo
    clone_url: https://example.invalid/demo-repo.git
    human_workspace_root: {str(tmp_path / 'human').replace('\\', '/')}
    bot_workspace_root: {str(bot_root).replace('\\', '/')}
    webhook_secret_env: BB_DEMO_WEBHOOK_SECRET
    bitbucket_token_env: BB_DEMO_API_TOKEN
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("PR_REVISOR_DATA_DIR", str(data_dir))
    monkeypatch.setenv("PR_REVISOR_VAR_DIR", str(var_dir))
    monkeypatch.setenv("PR_REVISOR_DB_PATH", str(data_dir / "reviewer.db"))
    monkeypatch.setenv("PR_REVISOR_REPOS_CONFIG", str(repos_path))
    monkeypatch.setenv("BB_DEMO_WEBHOOK_SECRET", webhook_secret)
    monkeypatch.setenv("BB_DEMO_API_TOKEN", "token-123")
    return {
        "data_dir": data_dir,
        "var_dir": var_dir,
        "repos_path": repos_path,
        "bot_root": bot_root,
    }
