"""Global OpenDota item timing distributions used for hero-specific timing scores."""

import asyncio
import json
import logging
import os
import tempfile
import time
from typing import Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

ItemTimings = Dict[int, Dict[str, List[dict]]]
_cache: Optional[ItemTimings] = None
_cache_time: float = 0.0
_lock = asyncio.Lock()


def _load_cache() -> None:
    global _cache, _cache_time
    path = settings.item_timing_cache_file
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        heroes = payload.get("heroes") or {}
        _cache = {
            int(hero_id): items
            for hero_id, items in heroes.items()
            if str(hero_id).isdigit() and isinstance(items, dict)
        }
        _cache_time = float(payload.get("updated_at") or 0)
    except Exception as exc:
        logger.warning("Could not read item timing cache: %s", exc)


def _save_cache() -> None:
    path = settings.item_timing_cache_file
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(
                {"updated_at": time.time(), "heroes": _cache or {}},
                f,
                ensure_ascii=False,
            )
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


async def _fetch_all() -> ItemTimings:
    url = settings.opendota_base_url.rstrip("/") + "/scenarios/itemTimings"
    headers = {
        "Accept": "application/json",
        "User-Agent": "dota-review-assistant/2.0",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
        response = await client.get(url, headers=headers)
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}")
    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError("unexpected itemTimings payload")

    result: ItemTimings = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        try:
            hero_id = int(row.get("hero_id"))
            item = str(row.get("item") or "")
            time_value = int(row.get("time"))
            games = int(row.get("games") or 0)
            wins = int(row.get("wins") or 0)
        except (TypeError, ValueError):
            continue
        if hero_id <= 0 or not item or games <= 0:
            continue
        result.setdefault(hero_id, {}).setdefault(item, []).append({
            "time": time_value,
            "games": games,
            "wins": wins,
        })
    for items in result.values():
        for rows in items.values():
            rows.sort(key=lambda item: item["time"])
    return result


async def get_item_timings() -> ItemTimings:
    global _cache, _cache_time
    ttl = settings.item_timing_cache_seconds
    if _cache is not None and (ttl <= 0 or time.time() - _cache_time <= ttl):
        return _cache

    async with _lock:
        if _cache is not None and (ttl <= 0 or time.time() - _cache_time <= ttl):
            return _cache
        if _cache is None:
            _load_cache()
        if _cache is not None and (ttl <= 0 or time.time() - _cache_time <= ttl):
            return _cache
        try:
            _cache = await _fetch_all()
            _cache_time = time.time()
            try:
                _save_cache()
            except Exception as exc:
                logger.warning("Could not write item timing cache: %s", exc)
        except Exception as exc:
            logger.warning("Could not fetch item timings: %s", exc)
            if _cache is None:
                _cache = {}
        return _cache


def timing_percentile(
    rows: Optional[List[dict]], seconds: int
) -> Optional[float]:
    """Return the empirical percentile of a purchase time, or None if too sparse."""
    if not rows:
        return None
    total = sum(int(row.get("games") or 0) for row in rows)
    if total < max(1, settings.item_timing_min_games):
        return None
    cumulative = sum(
        int(row.get("games") or 0)
        for row in rows
        if int(row.get("time", 0)) <= int(seconds)
    )
    return round(min(100.0, cumulative / total * 100), 1)
