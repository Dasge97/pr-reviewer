from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

import yaml

from service.models import PreparedWorkspace, ReviewConfig, ReviewDefaults, ReviewResult, WebhookIntake


logger = logging.getLogger("pr_revisor")


MAX_SUMMARY_CHARS = 280
MAX_REVIEW_BODY_CHARS = 1200
MAX_FINDINGS = 5
MAX_FINDING_CHARS = 160


def _truncate(text: str, max_chars: int) -> str:
    clean = (text or "").strip()
    if len(clean) <= max_chars:
        return clean
    suffix = "… (truncado)"
    if max_chars <= len(suffix):
        return clean[:max_chars]
    return clean[: max_chars - len(suffix)] + suffix


def _normalize_review_payload(data: dict[str, Any]) -> dict[str, Any]:
    findings = data.get("findings") or []
    if not isinstance(findings, list):
        findings = [str(findings)]

    normalized_findings = [_truncate(str(item), MAX_FINDING_CHARS) for item in findings[:MAX_FINDINGS]]

    return {
        **data,
        "summary": _truncate(str(data.get("summary", "")), MAX_SUMMARY_CHARS),
        "review_body": _truncate(str(data.get("review_body", "")), MAX_REVIEW_BODY_CHARS),
        "findings": normalized_findings,
    }


def load_repo_review_config(workspace_dir: Path, defaults: ReviewDefaults) -> ReviewConfig:
    config_path = workspace_dir / defaults.config_path
    if not config_path.exists():
        return ReviewConfig(
            prompt=defaults.prompt,
            include_paths=list(defaults.include_paths),
            exclude_paths=list(defaults.exclude_paths),
            requirements_file=defaults.requirements_file,
        )

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return ReviewConfig(
        prompt=raw.get("prompt", defaults.prompt),
        include_paths=list(raw.get("include_paths", defaults.include_paths)),
        exclude_paths=list(raw.get("exclude_paths", defaults.exclude_paths)),
        requirements_file=raw.get("requirements_file", defaults.requirements_file),
    )


def load_requirements_markdown(workspace_dir: Path, requirements_file: str) -> tuple[str, str | None]:
    candidates = [requirements_file, "requirements.md", "requerimientos.md"]
    for candidate in candidates:
        path = workspace_dir / candidate
        if path.exists() and path.is_file():
            return candidate, path.read_text(encoding="utf-8")
    return requirements_file, None


def build_review_prompt(
    intake: WebhookIntake,
    workspace: PreparedWorkspace,
    review_config: ReviewConfig,
    requirements_path: str,
    requirements_content: str | None,
) -> str:
    pr = intake.pull_request
    requirements_block = (
        f"Project requirements source: {requirements_path}\n"
        "Apply these requirements as highest priority before any other heuristic.\n"
        "--- REQUIREMENTS START ---\n"
        f"{requirements_content.strip()}\n"
        "--- REQUIREMENTS END ---"
        if requirements_content
        else (
            f"Project requirements source: {requirements_path}\n"
            "Requirements file not found in workspace. Continue with generic review rules."
        )
    )

    return "\n".join(
        [
            "You are reviewing a Bitbucket pull request from a local checkout.",
            f"Repository: {pr.workspace}/{pr.repo_slug}",
            f"PR: #{pr.pr_id} - {pr.title}",
            f"Source branch: {pr.source_branch} @ {pr.source_commit}",
            f"Target branch: {pr.target_branch} @ {pr.target_commit}",
            f"Workspace path: {workspace.workspace_dir}",
            f"Include paths: {', '.join(review_config.include_paths) or '(all)'}",
            f"Exclude paths: {', '.join(review_config.exclude_paths) or '(none)'}",
            requirements_block,
            "Instructions:",
            review_config.prompt,
            "Return JSON only with fields: status, summary, review_body, findings.",
            "status must be one of: approved, changes_requested, comment.",
            "findings must be an array of strings.",
        ]
    )


def parse_review_output(output: str) -> ReviewResult:
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        if "```json" in output:
            start = output.index("```json") + len("```json")
            end = output.index("```", start)
            data = json.loads(output[start:end].strip())
        else:
            raise ValueError("opencode output is not valid JSON")

    missing = [key for key in ("status", "summary", "review_body", "findings") if key not in data]
    if missing:
        raise ValueError(f"opencode output missing fields: {', '.join(missing)}")
    normalized = _normalize_review_payload(data)
    result = ReviewResult.model_validate({**normalized, "raw_output": output})
    return result


def run_review(intake: WebhookIntake, workspace: PreparedWorkspace) -> ReviewResult:
    defaults = intake.repo.review
    review_config = load_repo_review_config(workspace.workspace_dir, defaults)
    requirements_path, requirements_content = load_requirements_markdown(workspace.workspace_dir, review_config.requirements_file)
    prompt = build_review_prompt(intake, workspace, review_config, requirements_path, requirements_content)
    logger.info(
        "review.start repo=%s/%s pr=%s command=%s requirements=%s",
        intake.pull_request.workspace,
        intake.pull_request.repo_slug,
        intake.pull_request.pr_id,
        " ".join(defaults.opencode_command),
        requirements_path,
    )
    completed = subprocess.run(
        defaults.opencode_command,
        input=prompt,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(workspace.workspace_dir),
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"opencode failed: {completed.stderr.strip() or completed.stdout.strip()}")
    stdout = (completed.stdout or "").strip()
    if not stdout:
        raise RuntimeError(f"opencode returned empty output: {((completed.stderr or '').strip())[:500]}")
    logger.info(
        "review.finish repo=%s/%s pr=%s stdout_chars=%s",
        intake.pull_request.workspace,
        intake.pull_request.repo_slug,
        intake.pull_request.pr_id,
        len(stdout),
    )
    return parse_review_output(stdout)
