import asyncio
import logging
import time
from typing import Dict, Optional


logger = logging.getLogger(__name__)


class AnalysisJobManager:
    def __init__(self):
        self._jobs: Dict[int, dict] = {}
        self._lock = asyncio.Lock()

    async def start_job(self, match_id: int, runner) -> dict:
        async with self._lock:
            job = self._jobs.get(match_id)
            if job is None:
                job = self._new_job(match_id)
                self._jobs[match_id] = job

            if job["status"] in {"queued", "running"}:
                return dict(job)

            job["status"] = "queued"
            job["message"] = "任务已加入队列"
            job["error"] = None
            job["started_at"] = None
            job["finished_at"] = None
            job["updated_at"] = time.time()

            asyncio.create_task(runner(match_id))
            return dict(job)

    async def mark_running(self, match_id: int, message: str) -> None:
        await self._update(match_id, status="running", message=message, started_at=time.time())

    async def set_progress(self, match_id: int, message: str) -> None:
        await self._update(match_id, status="running", message=message)

    async def mark_completed(self, match_id: int, message: str = "分析完成") -> None:
        await self._update(
            match_id,
            status="completed",
            message=message,
            finished_at=time.time(),
            error=None,
        )

    async def mark_failed(self, match_id: int, message: str) -> None:
        await self._update(
            match_id,
            status="failed",
            message=message,
            error=message,
            finished_at=time.time(),
        )

    async def get_job(self, match_id: int) -> Optional[dict]:
        async with self._lock:
            job = self._jobs.get(match_id)
            return dict(job) if job else None

    async def _update(self, match_id: int, **fields) -> None:
        async with self._lock:
            job = self._jobs.get(match_id)
            if job is None:
                job = self._new_job(match_id)
                self._jobs[match_id] = job
            job.update(fields)
            job["updated_at"] = time.time()

    def _new_job(self, match_id: int) -> dict:
        now = time.time()
        return {
            "match_id": match_id,
            "status": "idle",
            "message": "等待开始",
            "error": None,
            "result_url": f"/match/{match_id}",
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
        }


_job_manager: Optional[AnalysisJobManager] = None


def get_job_manager() -> AnalysisJobManager:
    global _job_manager
    if _job_manager is None:
        _job_manager = AnalysisJobManager()
    return _job_manager
