import asyncio
import time
from typing import TYPE_CHECKING, Dict, List, Tuple

from app.utils.zh_names import HERO_ZH

if TYPE_CHECKING:
    from app.services.opendota import OpenDotaClient

_hero_data_cache: Dict[int, dict] = {}
_hero_data_time: float = 0.0
_CACHE_TTL = 86400.0
_lock = asyncio.Lock()


def _cache_fresh() -> bool:
    return bool(_hero_data_cache) and (time.time() - _hero_data_time) < _CACHE_TTL


async def get_hero_data(client: "OpenDotaClient") -> Dict[int, dict]:
    global _hero_data_cache, _hero_data_time
    if _cache_fresh():
        return _hero_data_cache
    async with _lock:
        if _cache_fresh():
            return _hero_data_cache
        _hero_data_cache = await client.fetch_hero_data()
        _hero_data_time = time.time()
    return _hero_data_cache


async def get_hero_maps(
    client: "OpenDotaClient",
) -> Tuple[Dict[int, str], Dict[int, List[str]]]:
    data = await get_hero_data(client)
    names = {
        hero_id: hero.get("localized_name", f"英雄#{hero_id}")
        for hero_id, hero in data.items()
    }
    roles = {
        hero_id: list(hero.get("roles") or [])
        for hero_id, hero in data.items()
    }
    return names, roles


async def get_hero_map(client: "OpenDotaClient") -> Dict[int, str]:
    names, _roles = await get_hero_maps(client)
    return names


def resolve_hero_name(hero_id: int, hero_map: Dict[int, str]) -> str:
    return HERO_ZH.get(hero_id) or hero_map.get(hero_id, f"英雄#{hero_id}")
