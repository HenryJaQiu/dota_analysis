import time
from typing import Dict, TYPE_CHECKING

from app.utils.zh_names import HERO_ZH

if TYPE_CHECKING:
    from app.services.opendota import OpenDotaClient

_hero_cache: Dict[int, str] = {}
_hero_cache_time: float = 0.0
_CACHE_TTL = 86400.0


async def get_hero_map(client: "OpenDotaClient") -> Dict[int, str]:
    global _hero_cache, _hero_cache_time
    if _hero_cache and (time.time() - _hero_cache_time) < _CACHE_TTL:
        return _hero_cache
    _hero_cache = await client.fetch_heroes()
    _hero_cache_time = time.time()
    return _hero_cache


def resolve_hero_name(hero_id: int, hero_map: Dict[int, str]) -> str:
    return HERO_ZH.get(hero_id) or hero_map.get(hero_id, f"英雄#{hero_id}")
