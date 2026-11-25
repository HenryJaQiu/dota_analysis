"""OpenDota Explorer queries for hero-pair lane matchup stats."""

import asyncio
import json
import logging
import os
import tempfile
import time
from typing import Dict, Iterable, Optional, Tuple

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

LaneKey = Tuple[int, int, int]
_cache_lock = asyncio.Lock()
_memory: Dict[str, Dict[str, float]] = {}
_memory_time: float = 0.0


def _cache_fresh(now: float) -> bool:
    ttl = settings.lane_matchup_cache_seconds
    return bool(_memory) and (ttl <= 0 or now - _memory_time <= ttl)


def _load_cache() -> None:
    global _memory, _memory_time
    path = settings.lane_matchup_cache_file
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        pairs = payload.get("pairs") or {}
        if isinstance(pairs, dict):
            _memory = pairs
            _memory_time = float(payload.get("updated_at") or 0)
    except Exception as exc:
        logger.warning("Could not read lane matchup cache: %s", exc)


def _save_cache() -> None:
    path = settings.lane_matchup_cache_file
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(
                {"updated_at": time.time(), "pairs": _memory},
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


def _key(pair: LaneKey) -> str:
    return f"{int(pair[0])}:{int(pair[1])}:{int(pair[2])}"


async def _query_pairs(
    pairs: Iterable[LaneKey],
) -> Optional[Dict[str, Dict[str, float]]]:
    pair_list = sorted(set(pairs))
    if not pair_list:
        return {}

    values = ", ".join(
        f"({int(hero)}, {int(opponent)}, {int(role)})"
        for hero, opponent, role in pair_list
    )
    sql = f"""
SELECT pm.hero_id,
       opp.hero_id AS opp_hero_id,
       pm.lane_role,
       count(*) AS games,
       sum(CASE WHEN m.radiant_win = (pm.player_slot < 128) THEN 1 ELSE 0 END) AS wins
FROM player_matches pm
JOIN player_matches opp
  ON opp.match_id = pm.match_id AND opp.lane = pm.lane
JOIN matches m ON m.match_id = pm.match_id
WHERE (opp.player_slot < 128) <> (pm.player_slot < 128)
  AND (pm.hero_id, opp.hero_id, pm.lane_role) IN ({values})
GROUP BY pm.hero_id, opp.hero_id, pm.lane_role
"""
    url = settings.opendota_base_url.rstrip("/") + "/explorer"
    headers = {
        "Accept": "application/json",
        "User-Agent": "dota-review-assistant/2.0",
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
            response = await client.get(url, params={"sql": sql}, headers=headers)
        if response.status_code != 200:
            logger.warning("Explorer lane matchup HTTP %s", response.status_code)
            return None
        payload = response.json()
    except Exception as exc:
        logger.warning("Explorer lane matchup query failed: %s", exc)
        return None

    result: Dict[str, Dict[str, float]] = {}
    for row in payload.get("rows") or []:
        if not isinstance(row, dict):
            continue
        try:
            hero = int(row.get("hero_id"))
            opponent = int(row.get("opp_hero_id"))
            role = int(row.get("lane_role"))
            games = int(row.get("games") or 0)
            wins = int(row.get("wins") or 0)
        except (TypeError, ValueError):
            continue
        if games <= 0:
            continue
        result[_key((hero, opponent, role))] = {
            "games": games,
            "wins": wins,
            "win_rate": round(wins / games * 100, 1),
        }
    return result


async def get_lane_matchups(
    pairs: Iterable[LaneKey],
) -> Dict[LaneKey, Dict[str, float]]:
    """Return {(hero_id, opponent_hero_id, lane_role): stats}."""
    global _memory, _memory_time
    unique_pairs = {tuple(int(value) for value in pair) for pair in pairs}
    if not unique_pairs:
        return {}

    async with _cache_lock:
        now = time.time()
        if _memory_time <= 0:
            _load_cache()
        if not _cache_fresh(now):
            _memory = {}
            _memory_time = now

        missing = [
            pair
            for pair in unique_pairs
            if _key(pair) not in _memory
        ]
        for start in range(0, len(missing), 30):
            chunk = missing[start:start + 30]
            fetched = await _query_pairs(chunk)
            if fetched is None:
                break
            for pair in chunk:
                key = _key(pair)
                _memory[key] = fetched.get(
                    key,
                    {"games": 0, "wins": 0, "win_rate": 50.0},
                )
        if missing:
            _memory_time = now
            try:
                _save_cache()
            except Exception as exc:
                logger.warning("Could not write lane matchup cache: %s", exc)

        return {
            pair: _memory.get(
                _key(pair),
                {"games": 0, "wins": 0, "win_rate": 50.0},
            )
            for pair in unique_pairs
        }
