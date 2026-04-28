from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


SUPPORTED_EVENTS = {"pullrequest:created", "pullrequest:updated", "pullrequest:reopened"}


class ReviewDefaults(BaseModel):
    prompt: str = "Review this Bitbucket pull request for correctness, risk, and missing tests."
    include_paths: list[str] = Field(default_factory=list)
    exclude_paths: list[str] = Field(default_factory=list)
    config_path: str = ".pr-reviewer.yml"
    requirements_file: str = "requerimientos.md"
    opencode_command: list[str] = Field(default_factory=lambda: ["opencode", "run"])


class RepoRegistration(BaseModel):
    workspace: str
    slug: str
    clone_url: str
    bitbucket_api_base: str = "https://api.bitbucket.org/2.0"
    human_workspace_root: str
    bot_workspace_root: str
    webhook_secret_env: str
    bitbucket_token_env: str
    review: ReviewDefaults = Field(default_factory=ReviewDefaults)

    @property
    def repo_key(self) -> str:
        return f"{self.workspace}/{self.slug}"


class RepoConfigFile(BaseModel):
    repos: list[RepoRegistration]
    defaults: ReviewDefaults = Field(default_factory=ReviewDefaults)


class ServiceSettings(BaseModel):
    app_env: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = Path("data")
    var_dir: Path = Path("var")
    repos_config_path: Path = Path("config/repos.yaml")
    db_path: Path = Path("data/reviewer.db")
    log_level: str = "INFO"
    worker_concurrency: int = 1


class PullRequestRef(BaseModel):
    workspace: str
    repo_slug: str
    pr_id: int
    title: str
    source_branch: str
    source_commit: str
    target_branch: str
    target_commit: str
    updated_on: str | None = None
    author: str | None = None
    link: str | None = None

    @property
    def repo_key(self) -> str:
        return f"{self.workspace}/{self.repo_slug}"


class WebhookIntake(BaseModel):
    event_type: str
    delivery_id: str | None = None
    signature: str | None = None
    repo: RepoRegistration
    pull_request: PullRequestRef
    raw_payload: dict[str, Any]

    def idempotency_key(self) -> str:
        pr = self.pull_request
        revision_marker = pr.updated_on or f"{pr.source_commit}:{pr.target_commit}"
        return ":".join(
            [
                pr.workspace,
                pr.repo_slug,
                str(pr.pr_id),
                self.event_type,
                revision_marker,
            ]
        )

    @property
    def pr_key(self) -> str:
        pr = self.pull_request
        return f"{pr.workspace}:{pr.repo_slug}:{pr.pr_id}"


class ReviewConfig(BaseModel):
    prompt: str
    include_paths: list[str] = Field(default_factory=list)
    exclude_paths: list[str] = Field(default_factory=list)
    requirements_file: str = "requerimientos.md"


class ReviewResult(BaseModel):
    status: Literal["approved", "changes_requested", "comment"]
    summary: str
    review_body: str
    findings: list[str] = Field(default_factory=list)
    raw_output: str = ""


@dataclass(slots=True)
class PreparedWorkspace:
    mirror_dir: Path
    workspace_dir: Path
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class JobRecord:
    id: int
    repo_key: str
    pr_key: str
    workspace: str
    repo_slug: str
    pr_id: int
    event_key: str
    status: str
    attempt_count: int
