from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from service.models import JobRecord, PullRequestRef, ReviewResult, WebhookIntake


SCHEMA = """
CREATE TABLE IF NOT EXISTS webhook_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT NOT NULL UNIQUE,
    delivery_id TEXT,
    workspace TEXT NOT NULL,
    repo_slug TEXT NOT NULL,
    pr_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    source_commit TEXT NOT NULL,
    target_commit TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pull_requests (
    repo_key TEXT NOT NULL,
    pr_key TEXT NOT NULL PRIMARY KEY,
    workspace TEXT NOT NULL,
    repo_slug TEXT NOT NULL,
    pr_id INTEGER NOT NULL,
    title TEXT,
    source_branch TEXT,
    source_commit TEXT,
    target_branch TEXT,
    target_commit TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    last_job_id INTEGER,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS review_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT NOT NULL UNIQUE,
    repo_key TEXT NOT NULL,
    pr_key TEXT NOT NULL,
    workspace TEXT NOT NULL,
    repo_slug TEXT NOT NULL,
    pr_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    retriable INTEGER NOT NULL DEFAULT 1,
    review_status TEXT,
    review_summary TEXT,
    review_body TEXT,
    raw_output TEXT,
    error_stage TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS repo_comments (
    pr_key TEXT NOT NULL PRIMARY KEY,
    comment_id TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pr_locks (
    pr_key TEXT NOT NULL PRIMARY KEY,
    job_id INTEGER NOT NULL,
    locked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class StateStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()

    def init_schema(self) -> None:
        with self._conn:
            self._conn.executescript(SCHEMA)

    def register_webhook_event(self, intake: WebhookIntake) -> tuple[bool, int | None]:
        pr = intake.pull_request
        with self._lock, self._conn:
            existing = self._conn.execute(
                "SELECT id FROM review_jobs WHERE event_key = ?",
                (intake.idempotency_key(),),
            ).fetchone()
            if existing:
                return False, existing["id"]

            self._conn.execute(
                """
                INSERT INTO webhook_events (
                    event_key, delivery_id, workspace, repo_slug, pr_id, event_type,
                    source_commit, target_commit, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intake.idempotency_key(),
                    intake.delivery_id,
                    pr.workspace,
                    pr.repo_slug,
                    pr.pr_id,
                    intake.event_type,
                    pr.source_commit,
                    pr.target_commit,
                    json.dumps(intake.raw_payload),
                ),
            )
            self._conn.execute(
                """
                INSERT INTO pull_requests (
                    repo_key, pr_key, workspace, repo_slug, pr_id, title, source_branch,
                    source_commit, target_branch, target_commit, status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', CURRENT_TIMESTAMP)
                ON CONFLICT(pr_key) DO UPDATE SET
                    title=excluded.title,
                    source_branch=excluded.source_branch,
                    source_commit=excluded.source_commit,
                    target_branch=excluded.target_branch,
                    target_commit=excluded.target_commit,
                    status='queued',
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    pr.repo_key,
                    intake.pr_key,
                    pr.workspace,
                    pr.repo_slug,
                    pr.pr_id,
                    pr.title,
                    pr.source_branch,
                    pr.source_commit,
                    pr.target_branch,
                    pr.target_commit,
                ),
            )
            cursor = self._conn.execute(
                """
                INSERT INTO review_jobs (
                    event_key, repo_key, pr_key, workspace, repo_slug, pr_id, status
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    intake.idempotency_key(),
                    pr.repo_key,
                    intake.pr_key,
                    pr.workspace,
                    pr.repo_slug,
                    pr.pr_id,
                ),
            )
            job_id = cursor.lastrowid
            self._conn.execute(
                "UPDATE pull_requests SET last_job_id = ?, updated_at = CURRENT_TIMESTAMP WHERE pr_key = ?",
                (job_id, intake.pr_key),
            )
            return True, job_id

    def claim_next_job(self) -> JobRecord | None:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT * FROM review_jobs WHERE status = 'pending' ORDER BY id LIMIT 1"
            ).fetchone()
            if not row:
                return None
            self._conn.execute(
                "UPDATE review_jobs SET status = 'running', attempt_count = attempt_count + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (row["id"],),
            )
            self._conn.execute(
                "UPDATE pull_requests SET status = 'running', updated_at = CURRENT_TIMESTAMP WHERE pr_key = ?",
                (row["pr_key"],),
            )
            return JobRecord(
                id=row["id"],
                repo_key=row["repo_key"],
                pr_key=row["pr_key"],
                workspace=row["workspace"],
                repo_slug=row["repo_slug"],
                pr_id=row["pr_id"],
                event_key=row["event_key"],
                status="running",
                attempt_count=row["attempt_count"] + 1,
            )

    def acquire_pr_lock(self, pr_key: str, job_id: int) -> bool:
        with self._lock, self._conn:
            row = self._conn.execute("SELECT job_id FROM pr_locks WHERE pr_key = ?", (pr_key,)).fetchone()
            if row:
                return False
            self._conn.execute("INSERT INTO pr_locks (pr_key, job_id) VALUES (?, ?)", (pr_key, job_id))
            return True

    def release_pr_lock(self, pr_key: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM pr_locks WHERE pr_key = ?", (pr_key,))

    def mark_job_success(self, job_id: int, result: ReviewResult) -> None:
        with self._lock, self._conn:
            row = self._conn.execute("SELECT pr_key FROM review_jobs WHERE id = ?", (job_id,)).fetchone()
            self._conn.execute(
                """
                UPDATE review_jobs
                SET status = 'completed', retriable = 0, review_status = ?, review_summary = ?,
                    review_body = ?, raw_output = ?, error_stage = NULL, error_message = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (result.status, result.summary, result.review_body, result.raw_output, job_id),
            )
            if row:
                self._conn.execute(
                    "UPDATE pull_requests SET status = 'completed', updated_at = CURRENT_TIMESTAMP WHERE pr_key = ?",
                    (row["pr_key"],),
                )

    def mark_job_failed(self, job_id: int, stage: str, message: str, retriable: bool = True) -> None:
        with self._lock, self._conn:
            row = self._conn.execute("SELECT pr_key FROM review_jobs WHERE id = ?", (job_id,)).fetchone()
            self._conn.execute(
                """
                UPDATE review_jobs
                SET status = 'failed', retriable = ?, error_stage = ?, error_message = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (1 if retriable else 0, stage, message, job_id),
            )
            if row:
                self._conn.execute(
                    "UPDATE pull_requests SET status = 'failed', updated_at = CURRENT_TIMESTAMP WHERE pr_key = ?",
                    (row["pr_key"],),
                )

    def mark_job_pending(self, job_id: int) -> None:
        with self._lock, self._conn:
            row = self._conn.execute("SELECT pr_key FROM review_jobs WHERE id = ?", (job_id,)).fetchone()
            self._conn.execute(
                "UPDATE review_jobs SET status = 'pending', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (job_id,),
            )
            if row:
                self._conn.execute(
                    "UPDATE pull_requests SET status = 'queued', updated_at = CURRENT_TIMESTAMP WHERE pr_key = ?",
                    (row["pr_key"],),
                )

    def store_comment_id(self, pr_key: str, comment_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO repo_comments (pr_key, comment_id, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(pr_key) DO UPDATE SET comment_id = excluded.comment_id, updated_at = CURRENT_TIMESTAMP
                """,
                (pr_key, comment_id),
            )

    def get_comment_id(self, pr_key: str) -> str | None:
        row = self._conn.execute("SELECT comment_id FROM repo_comments WHERE pr_key = ?", (pr_key,)).fetchone()
        return row["comment_id"] if row else None

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM review_jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def get_pr(self, pr_key: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM pull_requests WHERE pr_key = ?", (pr_key,)).fetchone()
        return dict(row) if row else None

    def list_jobs(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self._conn.execute("SELECT * FROM review_jobs ORDER BY id")]

    def load_intake_for_job(self, job: JobRecord, repo_lookup: dict[str, Any]) -> WebhookIntake:
        row = self._conn.execute("SELECT * FROM webhook_events WHERE event_key = ?", (job.event_key,)).fetchone()
        if not row:
            raise RuntimeError(f"Missing webhook event for job {job.id}")
        payload = json.loads(row["payload_json"])
        repo = repo_lookup[job.repo_key]
        pr = PullRequestRef(
            workspace=row["workspace"],
            repo_slug=row["repo_slug"],
            pr_id=row["pr_id"],
            title=payload["pullrequest"].get("title", ""),
            source_branch=payload["pullrequest"]["source"]["branch"]["name"],
            source_commit=payload["pullrequest"]["source"]["commit"]["hash"],
            target_branch=payload["pullrequest"]["destination"]["branch"]["name"],
            target_commit=payload["pullrequest"]["destination"]["commit"]["hash"],
            updated_on=payload["pullrequest"].get("updated_on") or payload["pullrequest"].get("created_on"),
            author=payload["pullrequest"].get("author", {}).get("display_name"),
            link=(payload["pullrequest"].get("links", {}).get("html", {}) or {}).get("href"),
        )
        return WebhookIntake(
            event_type=row["event_type"],
            delivery_id=row["delivery_id"],
            repo=repo,
            pull_request=pr,
            raw_payload=payload,
        )
