from __future__ import annotations

import asyncio


class ReviewQueue:
    def __init__(self, maxsize: int = 0):
        self._queue: asyncio.Queue[int] = asyncio.Queue(maxsize=maxsize)
        self._inflight_prs: set[str] = set()
        self._lock = asyncio.Lock()

    async def enqueue(self, job_id: int) -> None:
        await self._queue.put(job_id)

    async def get(self) -> int:
        return await self._queue.get()

    def task_done(self) -> None:
        self._queue.task_done()

    async def mark_active(self, pr_key: str) -> bool:
        async with self._lock:
            if pr_key in self._inflight_prs:
                return False
            self._inflight_prs.add(pr_key)
            return True

    async def clear_active(self, pr_key: str) -> None:
        async with self._lock:
            self._inflight_prs.discard(pr_key)
