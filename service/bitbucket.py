from __future__ import annotations

from dataclasses import dataclass

import httpx

from service.config import resolve_secret
from service.models import RepoRegistration, ReviewResult


def build_comment_marker(workspace: str, pr_id: int) -> str:
    return f"<!-- pr-revisor:{workspace}:{pr_id} -->"


def build_comment_body(workspace: str, pr_id: int, result: ReviewResult) -> str:
    marker = build_comment_marker(workspace, pr_id)
    findings = "\n".join(f"- {item}" for item in result.findings) if result.findings else "- No specific findings."
    return f"{marker}\n\n## {result.status.replace('_', ' ').title()}\n\n{result.summary}\n\n{result.review_body}\n\n### Findings\n{findings}\n"


@dataclass(slots=True)
class BitbucketClient:
    repo: RepoRegistration

    def _headers(self) -> dict[str, str]:
        token = resolve_secret(self.repo.bitbucket_token_env)
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _comments_url(self, pr_id: int, comment_id: str | None = None) -> str:
        base = f"{self.repo.bitbucket_api_base}/repositories/{self.repo.workspace}/{self.repo.slug}/pullrequests/{pr_id}/comments"
        return f"{base}/{comment_id}" if comment_id else base

    def upsert_comment(self, pr_id: int, result: ReviewResult, existing_comment_id: str | None = None) -> str:
        body = {"content": {"raw": build_comment_body(self.repo.workspace, pr_id, result)}}
        with httpx.Client(timeout=30.0) as client:
            if existing_comment_id:
                response = client.put(self._comments_url(pr_id, existing_comment_id), headers=self._headers(), json=body)
            else:
                response = client.post(self._comments_url(pr_id), headers=self._headers(), json=body)
            response.raise_for_status()
            data = response.json()
            return str(data["id"])
