"""Followed Steam players and their recent Dota 2 matches."""

import asyncio
import json
import logging
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote, unquote, urlparse

import httpx

from app.config import settings
from app.services.cache import get_cache
from app.services.opendota import MatchNotFoundError, OpenDotaAPIError, get_client
from app.utils.hero_names import get_hero_map, resolve_hero_name

logger = logging.getLogger(__name__)

STEAM64_BASE = 76561197960265728
MAX_ACCOUNT_ID = 0xFFFFFFFF

STEAM2_RE = re.compile(r"^STEAM_[0-5]:([01]):(\d+)$", re.IGNORECASE)
STEAM3_RE = re.compile(r"^\[?U:1:(\d+)\]?$", re.IGNORECASE)
VANITY_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")

GAME_MODE_NAMES = {
    1: "全英雄选择",
    2: "队长模式",
    3: "随机征召",
    4: "单中",
    5: "全随机",
    22: "天梯全英雄选择",
    23: "加速模式",
}


class FollowError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class SteamInput:
    account_id: Optional[int] = None
    steam_id64: Optional[int] = None
    vanity: Optional[str] = None
    source: str = "account_id"


def _from_steam64(value: Any) -> SteamInput:
    try:
        steam_id64 = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise FollowError("SteamID64 格式不正确") from exc
    account_id = steam_id64 - STEAM64_BASE
    if account_id <= 0 or account_id > MAX_ACCOUNT_ID:
        raise FollowError("SteamID64 不在有效范围内")
    return SteamInput(
        account_id=account_id,
        steam_id64=steam_id64,
        source="steam64",
    )


def _from_account_id(value: Any, source: str = "account_id") -> SteamInput:
    try:
        account_id = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise FollowError("Dota 2 账号 ID 格式不正确") from exc
    if account_id <= 0 or account_id > MAX_ACCOUNT_ID:
        raise FollowError("Dota 2 账号 ID 不在有效范围内")
    return SteamInput(
        account_id=account_id,
        steam_id64=STEAM64_BASE + account_id,
        source=source,
    )


def _from_vanity(value: str) -> SteamInput:
    vanity = unquote(value).strip()
    if not VANITY_RE.match(vanity):
        raise FollowError("Steam 自定义主页名称格式不正确")
    return SteamInput(vanity=vanity, source="vanity")


def parse_steam_input(value: str) -> SteamInput:
    """Accept friend code, account id, SteamID64, Steam2/3 or profile URL."""
    raw = (value or "").strip()
    if not raw:
        raise FollowError("请输入 Steam 好友 ID、SteamID64 或个人主页链接")

    lowered = raw.lower()
    if "steamcommunity.com" in lowered:
        if not lowered.startswith(("http://", "https://")):
            raw = "https://" + raw
        parsed = urlparse(raw)
        if parsed.netloc.lower() not in {"steamcommunity.com", "www.steamcommunity.com"}:
            raise FollowError("只支持 steamcommunity.com 的个人主页链接")
        parts = [unquote(part) for part in parsed.path.split("/") if part]
        if len(parts) < 2:
            raise FollowError("无法识别该 Steam 主页链接")
        kind, target = parts[0].lower(), parts[1]
        if kind == "profiles":
            return _from_steam64(target)
        if kind == "id":
            return _from_vanity(target)
        raise FollowError("无法识别该 Steam 主页链接")

    if "://" in raw:
        raise FollowError("只支持 Steam 官方个人主页链接，请填写好友 ID 或 SteamID64")

    match = STEAM2_RE.match(raw)
    if match:
        auth, account = int(match.group(1)), int(match.group(2))
        return _from_account_id(account * 2 + auth, source="steam2")

    match = STEAM3_RE.match(raw)
    if match:
        return _from_account_id(match.group(1), source="steam3")

    if raw.isdigit():
        number = int(raw)
        if len(raw) >= 17 or number >= STEAM64_BASE:
            return _from_steam64(number)
        return _from_account_id(number)

    if VANITY_RE.match(raw):
        return _from_vanity(raw)

    raise FollowError("无法识别该 ID，请填写好友代码、SteamID64 或个人主页链接")


async def _resolve_vanity(vanity: str) -> SteamInput:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) dota-review-assistant/2.0"
    }
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=10.0),
        follow_redirects=True,
        headers=headers,
    ) as client:
        if settings.steam_api_key:
            try:
                response = await client.get(
                    "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/",
                    params={
                        "key": settings.steam_api_key,
                        "vanityurl": vanity,
                    },
                )
                if response.status_code == 200:
                    payload = response.json()
                    result = payload.get("response") or {}
                    if result.get("success") == 1 and result.get("steamid"):
                        return _from_steam64(result["steamid"])
            except Exception as exc:
                logger.info("Steam vanity API failed: %s", exc)

        try:
            response = await client.get(
                f"https://steamcommunity.com/id/{quote(vanity, safe='')}/?xml=1"
            )
            if response.status_code == 200:
                match = re.search(r"<steamID64>(\d+)</steamID64>", response.text)
                if match:
                    return _from_steam64(match.group(1))
        except Exception as exc:
            logger.info("Steam community XML failed: %s", exc)

    raise FollowError(
        "无法解析该 Steam 自定义主页，请直接填写好友 ID 或 SteamID64"
    )


async def resolve_steam_identity(value: str) -> SteamInput:
    parsed = parse_steam_input(value)
    if parsed.account_id is not None:
        return parsed
    assert parsed.vanity is not None
    return await _resolve_vanity(parsed.vanity)


class FollowStore:
    def __init__(self, path: Optional[str] = None):
        self.path = path or settings.follows_file
        self._lock = threading.RLock()

    def _load(self) -> Dict[str, Any]:
        if not os.path.exists(self.path):
            return {"version": 1, "players": []}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or not isinstance(data.get("players"), list):
                return {"version": 1, "players": []}
            return data
        except Exception as exc:
            logger.warning("Could not read follows file %s: %s", self.path, exc)
            return {"version": 1, "players": []}

    def _save(self, data: Dict[str, Any]) -> None:
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._load().get("players", []))

    def add(self, player: Dict[str, Any]) -> None:
        with self._lock:
            data = self._load()
            data.setdefault("players", []).append(player)
            data["version"] = 1
            self._save(data)

    def update(self, account_id: int, **fields: Any) -> None:
        with self._lock:
            data = self._load()
            for player in data.get("players", []):
                if int(player.get("account_id", 0)) == int(account_id):
                    fields.pop("account_id", None)
                    player.update(fields)
                    player["account_id"] = int(account_id)
                    break
            data["version"] = 1
            self._save(data)

    def remove(self, account_id: int) -> bool:
        with self._lock:
            data = self._load()
            players = data.get("players", [])
            kept = [
                player
                for player in players
                if int(player.get("account_id", 0)) != int(account_id)
            ]
            if len(kept) == len(players):
                return False
            data["players"] = kept
            self._save(data)
            return True


_store: Optional[FollowStore] = None
_refresh_lock = asyncio.Lock()


def get_follow_store() -> FollowStore:
    global _store
    if _store is None:
        _store = FollowStore()
    return _store


def _time_ago(timestamp: Any) -> str:
    try:
        value = float(timestamp or 0)
    except (TypeError, ValueError):
        value = 0
    if value <= 0:
        return "尚未更新"
    delta = max(0, int(time.time() - value))
    if delta < 60:
        return "刚刚"
    if delta < 3600:
        return f"{delta // 60} 分钟前"
    if delta < 86400:
        return f"{delta // 3600} 小时前"
    return f"{delta // 86400} 天前"


def _is_stale(player: Dict[str, Any], now: Optional[float] = None) -> bool:
    now = now or time.time()
    try:
        last = float(player.get("last_checked") or 0)
    except (TypeError, ValueError):
        last = 0
    return last <= 0 or (now - last) > settings.follows_refresh_seconds


def _normalize_match(
    item: Dict[str, Any],
    hero_map: Dict[int, str],
    analysis_cache,
) -> Optional[Dict[str, Any]]:
    try:
        match_id = int(item.get("match_id") or 0)
        player_slot = int(item.get("player_slot") or 0)
        hero_id = int(item.get("hero_id") or 0)
        start_time = int(item.get("start_time") or 0)
        duration = int(item.get("duration") or 0)
        kills = int(item.get("kills") or 0)
        deaths = int(item.get("deaths") or 0)
        assists = int(item.get("assists") or 0)
        game_mode = int(item.get("game_mode") or 0)
    except (TypeError, ValueError):
        return None
    if match_id <= 0:
        return None

    is_radiant = player_slot < 128
    won = bool(item.get("radiant_win")) == is_radiant
    return {
        "match_id": match_id,
        "hero_id": hero_id,
        "hero_name": resolve_hero_name(hero_id, hero_map),
        "won": won,
        "result": "胜" if won else "负",
        "kills": kills,
        "deaths": deaths,
        "assists": assists,
        "duration_minutes": round(duration / 60.0, 1) if duration else 0,
        "start_time": start_time,
        "played_at": (
            datetime.fromtimestamp(start_time).strftime("%m-%d %H:%M")
            if start_time
            else ""
        ),
        "time_ago": _time_ago(start_time),
        "game_mode": game_mode,
        "game_mode_name": GAME_MODE_NAMES.get(game_mode, ""),
        "analyzed": analysis_cache.exists(match_id),
    }


async def _fetch_follow_bundle(
    identity: SteamInput,
    *,
    nickname: str = "",
    existing: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    account_id = int(identity.account_id or 0)
    if account_id <= 0:
        raise FollowError("无效的 Dota 2 账号 ID")

    client = get_client()
    profile: Dict[str, Any] = {}
    try:
        player_data = await client.fetch_player(account_id)
        profile = player_data.get("profile") or {}
    except MatchNotFoundError:
        profile = {}
    except Exception as exc:
        logger.info("Could not load profile for %s: %s", account_id, exc)

    try:
        raw_matches = await client.fetch_player_matches(
            account_id, limit=settings.follows_match_limit
        )
    except MatchNotFoundError as exc:
        raise FollowError(
            "未找到该玩家的最近比赛，请检查 ID 或 Steam 隐私设置",
            status_code=404,
        ) from exc
    except OpenDotaAPIError as exc:
        raise FollowError(f"OpenDota 请求失败：{exc}", status_code=502) from exc

    hero_map: Dict[int, str] = {}
    try:
        hero_map = await get_hero_map(client)
    except Exception as exc:
        logger.info("Could not load hero names: %s", exc)

    analysis_cache = get_cache()
    matches = []
    for item in raw_matches:
        if isinstance(item, dict):
            normalized = _normalize_match(item, hero_map, analysis_cache)
            if normalized:
                matches.append(normalized)

    existing = existing or {}
    now = time.time()
    personaname = (
        profile.get("personaname")
        or existing.get("personaname")
        or nickname
        or f"玩家 {account_id}"
    )
    avatar = (
        profile.get("avatarfull")
        or profile.get("avatarmedium")
        or profile.get("avatar")
        or existing.get("avatar")
        or ""
    )
    steam_id64 = str(
        profile.get("steamid")
        or existing.get("steam_id64")
        or identity.steam_id64
        or (STEAM64_BASE + account_id)
    )

    return {
        "account_id": account_id,
        "steam_id64": steam_id64,
        "nickname": nickname or existing.get("nickname", ""),
        "personaname": str(personaname)[:64],
        "avatar": str(avatar),
        "added_at": existing.get("added_at", now),
        "last_checked": now,
        "matches": matches,
        "error": None,
    }


def _public_follows(players: List[Dict[str, Any]]) -> Dict[str, Any]:
    now = time.time()
    analysis_cache = get_cache()
    result = []
    for player in players:
        if not isinstance(player, dict):
            continue
        item = dict(player)
        item["account_id"] = int(item.get("account_id") or 0)
        item["steam_id64"] = str(item.get("steam_id64") or "")
        raw_matches = item.get("matches")
        item["matches"] = raw_matches if isinstance(raw_matches, list) else []
        for match in item["matches"]:
            if isinstance(match, dict) and match.get("match_id"):
                try:
                    match["analyzed"] = analysis_cache.exists(int(match["match_id"]))
                except (TypeError, ValueError):
                    match["analyzed"] = False
        item["stale"] = _is_stale(item, now)
        item["updated_text"] = _time_ago(item.get("last_checked"))
        result.append(item)
    result.sort(key=lambda item: item.get("added_at", 0), reverse=True)
    return {
        "players": result,
        "needs_refresh": any(item["stale"] for item in result),
        "refresh_seconds": settings.follows_refresh_seconds,
        "max_follows": settings.follows_max,
    }


def list_follows() -> Dict[str, Any]:
    return _public_follows(get_follow_store().list())


async def add_follow(steam_input: str, nickname: str = "") -> Dict[str, Any]:
    store = get_follow_store()
    players = store.list()
    if len(players) >= settings.follows_max:
        raise FollowError(
            f"最多关注 {settings.follows_max} 位玩家，请先取消部分关注",
            status_code=400,
        )

    identity = await resolve_steam_identity(steam_input)
    if any(int(p.get("account_id", 0)) == identity.account_id for p in players):
        raise FollowError("已经关注过该玩家", status_code=409)

    cleaned_nickname = (nickname or "").strip()[:32]
    bundle = await _fetch_follow_bundle(
        identity,
        nickname=cleaned_nickname,
    )
    store.add(bundle)
    return bundle


def remove_follow(account_id: int) -> None:
    if not get_follow_store().remove(account_id):
        raise FollowError("没有找到该关注玩家", status_code=404)


async def refresh_follows(force: bool = False) -> Dict[str, Any]:
    async with _refresh_lock:
        store = get_follow_store()
        players = store.list()
        if not players:
            result = _public_follows(players)
            result.update({"refreshed": 0, "errors": []})
            return result

        now = time.time()
        targets = [
            player
            for player in players
            if force or _is_stale(player, now)
        ]
        if not targets:
            result = _public_follows(players)
            result.update({"refreshed": 0, "errors": []})
            return result

        semaphore = asyncio.Semaphore(4)
        errors: List[Dict[str, Any]] = []

        async def refresh_one(player: Dict[str, Any]) -> None:
            async with semaphore:
                account_id = int(player.get("account_id") or 0)
                identity = SteamInput(
                    account_id=account_id,
                    steam_id64=int(
                        player.get("steam_id64")
                        or (STEAM64_BASE + account_id)
                    ),
                    source="stored",
                )
                try:
                    bundle = await _fetch_follow_bundle(
                        identity,
                        nickname=player.get("nickname", ""),
                        existing=player,
                    )
                    store.update(
                        account_id,
                        personaname=bundle["personaname"],
                        avatar=bundle["avatar"],
                        steam_id64=bundle["steam_id64"],
                        last_checked=bundle["last_checked"],
                        matches=bundle["matches"],
                        error=None,
                    )
                except Exception as exc:
                    message = str(exc)[:220]
                    errors.append({
                        "account_id": account_id,
                        "personaname": player.get("personaname", ""),
                        "error": message,
                    })
                    store.update(
                        account_id,
                        last_checked=time.time(),
                        error=message,
                    )

        await asyncio.gather(*(refresh_one(player) for player in targets))
        result = _public_follows(store.list())
        result.update({"refreshed": len(targets), "errors": errors})
        return result
