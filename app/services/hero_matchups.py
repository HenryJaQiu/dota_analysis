"""Cached OpenDota hero matchup win rates used by lane evaluation."""

import asyncio
import json
import logging
import os
import tempfile
import time
from typing import Dict, Iterable, Optional

from app.config import settings

logger = logging.getLogger(__name__)

_memory: Dict[int, tuple[float, Dict[int, float]]] = {}
_lock = asyncio.Lock()


def _path(hero_id: int) -> str:
    return os.path.join(settings.hero_matchup_cache_dir, f"{int(hero_id)}.json")


def _read_disk(hero_id: int) -> Optional[Dict[int, float]]:
    path = _path(hero_id)
    if not os.path.exists(path):
        return None
    ttl = settings.hero_matchup_cache_seconds
    if ttl > 0 and time.time() - os.path.getmtime(path) > ttl:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        matchups = payload.get("matchups") or {}
        return {
            int(enemy): float(rate)
            for enemy, rate in matchups.items()
            if str(enemy).isdigit()
        }
    except Exception as exc:
        logger.warning("Could not read hero matchup cache %s: %s", path, exc)
        return None


def _write_disk(hero_id: int, matchups: Dict[int, float]) -> None:
    path = _path(hero_id)
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(
                {"updated_at": time.time(), "matchups": matchups},
                f,
                ensure_ascii=False,
                indent=2,
            )
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


async def _fetch(client, hero_id: int) -> Dict[int, float]:
    rows = await client.fetch_hero_matchups(hero_id)
    result: Dict[int, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            enemy_id = int(row.get("hero_id") or 0)
            games = int(row.get("games_played") or 0)
            wins = int(row.get("wins") or 0)
        except (TypeError, ValueError):
            continue
        if enemy_id > 0 and games > 0:
            result[enemy_id] = round(wins / games * 100, 1)
    return result


async def get_hero_matchups(
    client, hero_ids: Iterable[int]
) -> Dict[int, Dict[int, float]]:
    """Return {hero_id: {enemy_hero_id: win_rate_percent}} for lane opponents."""
    unique_ids = {int(hero_id) for hero_id in hero_ids if hero_id}
    result: Dict[int, Dict[int, float]] = {}
    ttl = settings.hero_matchup_cache_seconds
    now = time.time()

    for hero_id in unique_ids:
        cached = _memory.get(hero_id)
        if cached and (ttl <= 0 or now - cached[0] <= ttl):
            result[hero_id] = cached[1]
            continue

        disk = _read_disk(hero_id)
        if disk is not None:
            _memory[hero_id] = (now, disk)
            result[hero_id] = disk
            continue

        async with _lock:
            cached = _memory.get(hero_id)
            if cached and (ttl <= 0 or time.time() - cached[0] <= ttl):
                result[hero_id] = cached[1]
                continue
            try:
                matchups = await _fetch(client, hero_id)
                _memory[hero_id] = (time.time(), matchups)
                try:
                    _write_disk(hero_id, matchups)
                except Exception as exc:
                    logger.warning("Could not write hero matchup cache: %s", exc)
                result[hero_id] = matchups
            except Exception as exc:
                logger.info("Could not load matchups for hero %s: %s", hero_id, exc)

    return result
