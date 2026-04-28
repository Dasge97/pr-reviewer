from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from service.models import PreparedWorkspace, RepoRegistration, WebhookIntake


def _run_git(args: list[str], cwd: Path | None = None) -> None:
    subprocess.run(["git", *args], cwd=str(cwd) if cwd else None, check=True, capture_output=True, text=True)


def prepare_repo_storage(repo: RepoRegistration) -> tuple[Path, Path]:
    bot_root = Path(repo.bot_workspace_root)
    mirror_dir = bot_root / "repos" / f"{repo.slug}.git"
    workspace_root = bot_root / "workspaces" / repo.slug
    mirror_dir.parent.mkdir(parents=True, exist_ok=True)
    workspace_root.mkdir(parents=True, exist_ok=True)
    return mirror_dir, workspace_root


def sync_mirror(repo: RepoRegistration) -> Path:
    mirror_dir, _ = prepare_repo_storage(repo)
    if not mirror_dir.exists():
        _run_git(["clone", "--mirror", repo.clone_url, str(mirror_dir)])
    else:
        _run_git(["remote", "set-url", "origin", repo.clone_url], cwd=mirror_dir)
        _run_git(["fetch", "--prune", "origin"], cwd=mirror_dir)
    return mirror_dir


def prepare_pr_workspace(intake: WebhookIntake) -> PreparedWorkspace:
    repo = intake.repo
    pr = intake.pull_request
    mirror_dir, workspace_root = prepare_repo_storage(repo)
    if not mirror_dir.exists():
        sync_mirror(repo)
    else:
        _run_git(["fetch", "--prune", "origin"], cwd=mirror_dir)

    workspace_dir = workspace_root / f"pr-{pr.pr_id}"
    if not workspace_dir.exists():
        _run_git(["clone", str(mirror_dir), str(workspace_dir)])
    else:
        _run_git(["remote", "set-url", "origin", str(mirror_dir)], cwd=workspace_dir)

    _run_git(["fetch", "--prune", "origin"], cwd=workspace_dir)
    _run_git(["reset", "--hard"], cwd=workspace_dir)
    _run_git(["clean", "-fdx"], cwd=workspace_dir)
    _run_git(["checkout", "--force", pr.source_commit], cwd=workspace_dir)
    _run_git(["reset", "--hard", pr.source_commit], cwd=workspace_dir)

    return PreparedWorkspace(
        mirror_dir=mirror_dir,
        workspace_dir=workspace_dir,
        metadata={
            "source_commit": pr.source_commit,
            "target_commit": pr.target_commit,
            "pr_id": pr.pr_id,
        },
    )


def remove_workspace(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
