from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from service.bitbucket import BitbucketClient
from service.config import ensure_runtime_dirs, load_repo_config, load_settings, repo_index
from service.git_ops import prepare_pr_workspace
from service.models import RepoRegistration
from service.queue import ReviewQueue
from service.review_runner import run_review
from service.state import StateStore
from service.webhooks import parse_bitbucket_webhook


logger = logging.getLogger("pr_revisor")


class ServiceRuntime:
    def __init__(self) -> None:
        self.settings = load_settings()
        ensure_runtime_dirs(self.settings)
        self.repo_config = load_repo_config(self.settings.repos_config_path)
        self.repo_lookup = repo_index(self.repo_config)
        self.state = StateStore(self.settings.db_path)
        self.state.init_schema()
        self.queue = ReviewQueue()
        self.worker_task: asyncio.Task[Any] | None = None


async def _worker_loop(runtime: ServiceRuntime) -> None:
    while True:
        await runtime.queue.get()
        try:
            while True:
                job = runtime.state.claim_next_job()
                if not job:
                    break
                if not await runtime.queue.mark_active(job.pr_key):
                    runtime.state.mark_job_pending(job.id)
                    break
                try:
                    if not runtime.state.acquire_pr_lock(job.pr_key, job.id):
                        runtime.state.mark_job_pending(job.id)
                        continue
                    stage = "intake_load"
                    intake = runtime.state.load_intake_for_job(job, runtime.repo_lookup)
                    logger.info("job.start repo=%s pr=%s job=%s", job.repo_key, job.pr_id, job.id)

                    stage = "workspace_preparation"
                    workspace = prepare_pr_workspace(intake)
                    logger.info("job.workspace_prepared repo=%s pr=%s", job.repo_key, job.pr_id)

                    stage = "review_execution"
                    result = run_review(intake, workspace)
                    logger.info("job.review_ready repo=%s pr=%s status=%s", job.repo_key, job.pr_id, result.status)

                    stage = "comment_upsert"
                    comment_id = BitbucketClient(intake.repo).upsert_comment(job.pr_id, result, None)

                    stage = "completed"
                    runtime.state.mark_job_success(job.id, result)
                    logger.info("job.comment_created repo=%s pr=%s comment_id=%s", job.repo_key, job.pr_id, comment_id)
                except Exception as exc:  # pragma: no cover - exercised in tests via state
                    runtime.state.mark_job_failed(job.id, stage, str(exc), retriable=True)
                    logger.exception(
                        "job.failed stage=%s retriable=%s repo=%s pr=%s job=%s",
                        stage,
                        True,
                        job.repo_key,
                        job.pr_id,
                        job.id,
                    )
                finally:
                    runtime.state.release_pr_lock(job.pr_key)
                    await runtime.queue.clear_active(job.pr_key)
        finally:
            runtime.queue.task_done()


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = ServiceRuntime()
        app.state.runtime = runtime
        runtime.worker_task = asyncio.create_task(_worker_loop(runtime))
        try:
            yield
        finally:
            if runtime.worker_task:
                runtime.worker_task.cancel()
                try:
                    await runtime.worker_task
                except asyncio.CancelledError:
                    pass

    app = FastAPI(title="pr-revisor", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    async def _handle_bitbucket_webhook(request: Request) -> dict[str, Any]:
        runtime: ServiceRuntime = request.app.state.runtime
        intake = await parse_bitbucket_webhook(request, runtime.repo_lookup)
        admitted, job_id = runtime.state.register_webhook_event(intake)
        if not admitted:
            logger.info("webhook.duplicate repo=%s pr=%s key=%s", intake.pull_request.repo_key, intake.pull_request.pr_id, intake.idempotency_key())
            return {"status": "duplicate", "event_key": intake.idempotency_key(), "job_id": job_id}
        await runtime.queue.enqueue(job_id)
        logger.info("webhook.accepted repo=%s pr=%s key=%s", intake.pull_request.repo_key, intake.pull_request.pr_id, intake.idempotency_key())
        return {"status": "accepted", "event_key": intake.idempotency_key(), "job_id": job_id}

    @app.post("/webhooks/bitbucket")
    async def bitbucket_webhook(request: Request) -> dict[str, Any]:
        return await _handle_bitbucket_webhook(request)

    @app.post("/")
    async def bitbucket_webhook_root(request: Request) -> dict[str, Any]:
        return await _handle_bitbucket_webhook(request)

    return app


app = create_app()
