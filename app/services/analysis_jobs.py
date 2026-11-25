import asyncio
import logging
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)

KIND_ANALYSIS = "analysis"
KIND_PARSE = "parse"
KIND_REANALYZE = "reanalyze"


class AnalysisJobManager:
    """Small in-process job registry.

    Jobs are keyed by (kind, match_id) so a full match analysis and an
    AI-review-only refresh can run without overwriting each other's status.
    """

    def __init__(self):
        self._jobs: Dict[str, dict] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _key(match_id: int, kind: str) -> str:
        return f"{kind}:{match_id}"

    async def start_job(
        self,
        match_id: int,
        runner,
        kind: str = KIND_ANALYSIS,
    ) -> dict:
        async with self._lock:
            key = self._key(match_id, kind)
            job = self._jobs.get(key)
            if job is None:
                job = self._new_job(match_id, kind)
                self._jobs[key] = job

            if job["status"] in {"queued", "running"}:
                return dict(job)

            job["status"] = "queued"
            job["message"] = "任务已加入队列"
            job["error"] = None
            job["started_at"] = None
            job["finished_at"] = None
            job["updated_at"] = time.time()

            asyncio.create_task(self._supervise(runner, match_id, kind))
            return dict(job)

    async def _supervise(self, runner, match_id: int, kind: str) -> None:
        try:
            await runner(match_id)
        except asyncio.CancelledError:
            await self.mark_failed(match_id, "任务已取消", kind=kind)
            raise
        except Exception as exc:
            logger.exception("Background job %s:%s crashed", kind, match_id)
            await self.mark_failed(match_id, f"任务异常终止: {str(exc)[:200]}", kind=kind)

    async def mark_running(
        self, match_id: int, message: str, kind: str = KIND_ANALYSIS
    ) -> None:
        await self._update(
            match_id,
            kind=kind,
            status="running",
            message=message,
            started_at=time.time(),
        )

    async def set_progress(
        self, match_id: int, message: str, kind: str = KIND_ANALYSIS
    ) -> None:
        await self._update(match_id, kind=kind, status="running", message=message)

    async def mark_completed(
        self,
        match_id: int,
        message: str = "分析完成",
        kind: str = KIND_ANALYSIS,
    ) -> None:
        await self._update(
            match_id,
            kind=kind,
            status="completed",
            message=message,
            finished_at=time.time(),
            error=None,
        )

    async def mark_failed(
        self, match_id: int, message: str, kind: str = KIND_ANALYSIS
    ) -> None:
        await self._update(
            match_id,
            kind=kind,
            status="failed",
            message=message,
            error=message,
            finished_at=time.time(),
        )

    async def get_job(
        self, match_id: int, kind: str = KIND_ANALYSIS
    ) -> Optional[dict]:
        async with self._lock:
            job = self._jobs.get(self._key(match_id, kind))
            return dict(job) if job else None

    async def _update(self, match_id: int, kind: str = KIND_ANALYSIS, **fields) -> None:
        async with self._lock:
            key = self._key(match_id, kind)
            job = self._jobs.get(key)
            if job is None:
                job = self._new_job(match_id, kind)
                self._jobs[key] = job
            fields.pop("kind", None)
            job.update(fields)
            job["updated_at"] = time.time()

    def _new_job(self, match_id: int, kind: str) -> dict:
        now = time.time()
        return {
            "match_id": match_id,
            "kind": kind,
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
