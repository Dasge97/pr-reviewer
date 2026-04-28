from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from fastapi import HTTPException, Request

from service.config import resolve_secret
from service.models import PullRequestRef, RepoRegistration, SUPPORTED_EVENTS, WebhookIntake


def _extract_repo_key(payload: dict[str, Any]) -> str:
    repo = payload.get("repository") or {}
    full_name = (repo.get("full_name") or "").strip()

    workspace = (
        (repo.get("workspace") or {}).get("slug")
        or (repo.get("owner") or {}).get("username")
        or (full_name.split("/", 1)[0] if "/" in full_name else "")
        or ""
    ).strip()

    slug = (
        repo.get("slug")
        or (full_name.split("/", 1)[1] if "/" in full_name else "")
        or repo.get("name")
        or ""
    ).strip()

    if not workspace or not slug:
        raise HTTPException(status_code=400, detail="Missing repository workspace/slug")
    return f"{workspace}/{slug}"


def _extract_pull_request(payload: dict[str, Any], repo: RepoRegistration) -> PullRequestRef:
    pullrequest = payload.get("pullrequest") or {}
    source = pullrequest.get("source") or {}
    destination = pullrequest.get("destination") or {}
    try:
        return PullRequestRef(
            workspace=repo.workspace,
            repo_slug=repo.slug,
            pr_id=int(pullrequest["id"]),
            title=pullrequest.get("title", ""),
            source_branch=source["branch"]["name"],
            source_commit=source["commit"]["hash"],
            target_branch=destination["branch"]["name"],
            target_commit=destination["commit"]["hash"],
            updated_on=pullrequest.get("updated_on") or pullrequest.get("created_on"),
            author=(pullrequest.get("author") or {}).get("display_name"),
            link=((pullrequest.get("links") or {}).get("html") or {}).get("href"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Malformed pull request payload") from exc


def _validate_signature(signature: str | None, body: bytes, secret: str) -> None:
    if not signature:
        raise HTTPException(status_code=401, detail="Missing webhook signature")
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


async def parse_bitbucket_webhook(request: Request, repo_lookup: dict[str, RepoRegistration]) -> WebhookIntake:
    event_type = request.headers.get("X-Event-Key")
    if event_type not in SUPPORTED_EVENTS:
        raise HTTPException(status_code=400, detail="Unsupported event")

    body = await request.body()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    repo_key = _extract_repo_key(payload)
    repo = repo_lookup.get(repo_key)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not registered")

    signature = request.headers.get("X-Hub-Signature")
    secret = resolve_secret(repo.webhook_secret_env)
    _validate_signature(signature, body, secret)

    intake = WebhookIntake(
        event_type=event_type,
        delivery_id=request.headers.get("X-Request-UUID") or request.headers.get("X-Hook-UUID"),
        signature=signature,
        repo=repo,
        pull_request=_extract_pull_request(payload, repo),
        raw_payload=payload,
    )
    return intake
