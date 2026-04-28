from __future__ import annotations

from service.config import load_repo_config, load_settings, repo_index


def test_load_settings_and_repo_defaults(runtime_env):
    settings = load_settings()
    repo_config = load_repo_config(settings.repos_config_path)
    repos = repo_index(repo_config)

    assert settings.db_path.name == "reviewer.db"
    assert "demo-workspace/demo-repo" in repos
    assert repo_config.repos[0].review.prompt == "Review carefully and return JSON only."
