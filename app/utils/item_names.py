import time
from typing import Dict, TYPE_CHECKING, Union

from app.utils.zh_names import ITEM_ZH

if TYPE_CHECKING:
    from app.services.opendota import OpenDotaClient

_item_cache: Dict[int, str] = {}
_item_cache_time: float = 0.0
_CACHE_TTL = 86400.0


async def get_item_map(client: "OpenDotaClient") -> Dict[int, str]:
    global _item_cache, _item_cache_time
    if _item_cache and (time.time() - _item_cache_time) < _CACHE_TTL:
        return _item_cache
    _item_cache = await client.fetch_items()
    _item_cache_time = time.time()
    return _item_cache


def resolve_item_name(item_ref: Union[int, str], item_map: Dict[int, str]) -> str:
    if not item_ref:
        return ""

    if isinstance(item_ref, str):
        item_key = item_ref
    else:
        item_key = item_map.get(item_ref)

    if not item_key:
        return f"道具#{item_ref}"
    return ITEM_ZH.get(item_key, item_key)


RANK_NAMES = {
    1: "先锋", 2: "先锋", 3: "先锋", 4: "先锋", 5: "先锋",
    11: "卫士", 12: "卫士", 13: "卫士", 14: "卫士", 15: "卫士",
    21: "中军", 22: "中军", 23: "中军", 24: "中军", 25: "中军",
    31: "统帅", 32: "统帅", 33: "统帅", 34: "统帅", 35: "统帅",
    41: "传奇", 42: "传奇", 43: "传奇", 44: "传奇", 45: "传奇",
    51: "万古流芳", 52: "万古流芳", 53: "万古流芳", 54: "万古流芳", 55: "万古流芳",
    61: "超凡入圣", 62: "超凡入圣", 63: "超凡入圣", 64: "超凡入圣", 65: "超凡入圣",
    71: "冠绝一世", 72: "冠绝一世", 73: "冠绝一世", 74: "冠绝一世", 75: "冠绝一世",
    80: "冠绝一世", 81: "冠绝一世", 82: "冠绝一世", 83: "冠绝一世", 84: "冠绝一世",
    90: "冠绝一世", 91: "冠绝一世", 92: "冠绝一世", 93: "冠绝一世", 94: "冠绝一世", 95: "冠绝一世",
    99: "冠绝一世",
}


def resolve_rank_name(rank_tier) -> str:
    if rank_tier is None:
        return "未知段位"

    stars = rank_tier % 10
    base = RANK_NAMES.get(rank_tier) or RANK_NAMES.get((rank_tier // 10) * 10)
    if base and stars:
        return f"{base} {stars}星"
    return base or "未知段位"
