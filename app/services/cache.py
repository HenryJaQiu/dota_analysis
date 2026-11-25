import json
import os
import time
import tempfile
import logging
from typing import Any, Optional

from app.config import settings
from app.models.analysis import MatchAnalysis

logger = logging.getLogger(__name__)
CURRENT_CACHE_VERSION = 4


class CacheManager:
    def __init__(self):
        self.cache_dir = settings.cache_dir
        self.raw_dir = settings.raw_cache_dir
        self.ttl = settings.cache_ttl_seconds
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.raw_dir, exist_ok=True)

    def _path(self, match_id: int) -> str:
        return os.path.join(self.cache_dir, f"{match_id}.json")

    def _raw_path(self, match_id: int) -> str:
        return os.path.join(self.raw_dir, f"{match_id}.json")

    def exists(self, match_id: int) -> bool:
        path = self._path(match_id)
        if not os.path.exists(path):
            return False
        # ttl <= 0 means keep local match archives forever.
        if self.ttl > 0 and time.time() - os.path.getmtime(path) > self.ttl:
            return False
        return True

    def get(self, match_id: int) -> Optional[MatchAnalysis]:
        if not self.exists(match_id):
            return None
        try:
            with open(self._path(match_id), "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("cache_version") != CURRENT_CACHE_VERSION:
                return None
            return MatchAnalysis.model_validate(data)
        except Exception as e:
            logger.warning(f"Cache read error for {match_id}: {e}")
            return None

    def _atomic_write_json(self, path: str, data: Any) -> None:
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def set(self, match_id: int, analysis: MatchAnalysis) -> None:
        try:
            data = analysis.model_dump(mode="json")
            data["cache_version"] = CURRENT_CACHE_VERSION
            self._atomic_write_json(self._path(match_id), data)
        except Exception as e:
            logger.warning(f"Cache write error for {match_id}: {e}")

    def save_raw(self, match_id: int, raw: Any) -> None:
        """Persist the raw OpenDota payload, including parsed replay fields."""
        try:
            data = raw.model_dump(mode="json") if hasattr(raw, "model_dump") else raw
            self._atomic_write_json(self._raw_path(match_id), data)
        except Exception as e:
            logger.warning(f"Raw cache write error for {match_id}: {e}")

    def get_raw(self, match_id: int) -> Optional[dict]:
        path = self._raw_path(match_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Raw cache read error for {match_id}: {e}")
            return None

    def invalidate(self, match_id: int) -> None:
        path = self._path(match_id)
        if os.path.exists(path):
            os.unlink(path)

    def list_recent(self, limit: int = 5) -> list:
        try:
            files = [
                f for f in os.listdir(self.cache_dir)
                if f.endswith(".json")
            ]
            files.sort(
                key=lambda f: os.path.getmtime(os.path.join(self.cache_dir, f)),
                reverse=True,
            )
            results = []
            for fname in files[:limit]:
                match_id = int(fname.replace(".json", ""))
                analysis = self.get(match_id)
                if analysis:
                    results.append({
                        "match_id": match_id,
                        "duration_minutes": round(analysis.duration_minutes, 1),
                        "radiant_win": analysis.radiant_win,
                        "analyzed_at": analysis.analyzed_at.strftime("%m-%d %H:%M"),
                        "parse_status": analysis.parse_status.value,
                    })
            return results
        except Exception as e:
            logger.warning(f"List recent error: {e}")
            return []


_cache: Optional[CacheManager] = None


def get_cache() -> CacheManager:
    global _cache
    if _cache is None:
        _cache = CacheManager()
    return _cache
