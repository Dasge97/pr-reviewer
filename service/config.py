from __future__ import annotations

import os
from pathlib import Path

import yaml

from service.models import RepoConfigFile, RepoRegistration, ReviewDefaults, ServiceSettings


def load_settings() -> ServiceSettings:
    data_dir = Path(os.getenv("PR_REVISOR_DATA_DIR", "data"))
    default_db = data_dir / "reviewer.db"
    return ServiceSettings(
        app_env=os.getenv("PR_REVISOR_ENV", "development"),
        host=os.getenv("PR_REVISOR_HOST", "127.0.0.1"),
        port=int(os.getenv("PR_REVISOR_PORT", "8000")),
        data_dir=data_dir,
        var_dir=Path(os.getenv("PR_REVISOR_VAR_DIR", "var")),
        repos_config_path=Path(os.getenv("PR_REVISOR_REPOS_CONFIG", "config/repos.yaml")),
        db_path=Path(os.getenv("PR_REVISOR_DB_PATH", str(default_db))),
        log_level=os.getenv("PR_REVISOR_LOG_LEVEL", "INFO"),
        worker_concurrency=int(os.getenv("PR_REVISOR_WORKER_CONCURRENCY", "1")),
    )


def ensure_runtime_dirs(settings: ServiceSettings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.var_dir.mkdir(parents=True, exist_ok=True)
    (settings.var_dir / "log").mkdir(parents=True, exist_ok=True)


def load_repo_config(path: Path) -> RepoConfigFile:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    defaults = ReviewDefaults.model_validate(raw.get("defaults", {}))
    repos = []
    for entry in raw.get("repos", []):
        merged_review = defaults.model_dump()
        merged_review.update(entry.get("review", {}))
        payload = dict(entry)
        payload["review"] = merged_review
        repos.append(RepoRegistration.model_validate(payload))
    return RepoConfigFile(repos=repos, defaults=defaults)


def repo_index(repo_config: RepoConfigFile) -> dict[str, RepoRegistration]:
    return {repo.repo_key: repo for repo in repo_config.repos}


def resolve_secret(env_name: str) -> str:
    value = os.getenv(env_name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {env_name}")
    return value
