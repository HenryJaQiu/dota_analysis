import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, Optional

import httpx

from app.config import settings
from app.models.match import RawMatch, ParseStatus
from app.utils.rate_limiter import TokenBucketRateLimiter

logger = logging.getLogger(__name__)


class MatchNotFoundError(Exception):
    pass


class OpenDotaAPIError(Exception):
    pass


class OpenDotaRateLimitError(OpenDotaAPIError):
    pass


class OpenDotaClient:
    def __init__(self):
        self._rate_limiter = TokenBucketRateLimiter(
            rate=settings.opendota_rate_limit, capacity=5.0
        )
        self._client = httpx.AsyncClient(
            base_url=settings.opendota_base_url,
            timeout=30.0,
        )

    async def close(self):
        await self._client.aclose()

    async def _get(self, path: str, max_retries: int = 3) -> Any:
        for attempt in range(max_retries):
            await self._rate_limiter.acquire()
            try:
                response = await self._client.get(path)
                if response.status_code == 404:
                    raise MatchNotFoundError(f"未找到该比赛记录: {path}")
                if response.status_code == 429:
                    wait = 2 ** attempt
                    logger.warning(f"OpenDota rate limit, waiting {wait}s")
                    await asyncio.sleep(wait)
                    continue
                response.raise_for_status()
                return response.json()
            except httpx.TimeoutException:
                if attempt == max_retries - 1:
                    raise OpenDotaAPIError("请求超时，请稍后重试")
                await asyncio.sleep(2)
            except MatchNotFoundError:
                raise
            except httpx.HTTPStatusError as e:
                raise OpenDotaAPIError(f"OpenDota API 错误: {e.response.status_code}")
        raise OpenDotaRateLimitError("达到重试上限")

    async def _post(self, path: str) -> Optional[dict]:
        await self._rate_limiter.acquire()
        try:
            response = await self._client.post(path)
            if response.status_code in (200, 202):
                try:
                    return response.json()
                except Exception:
                    return {}
            return None
        except Exception as e:
            logger.warning(f"POST {path} failed: {e}")
            return None

    async def fetch_match(self, match_id: int) -> RawMatch:
        data = await self._get(f"/matches/{match_id}")
        return RawMatch(**data)

    async def request_parse(self, match_id: int) -> bool:
        result = await self._post(f"/request/{match_id}")
        return result is not None

    def detect_parse_status(self, match: RawMatch) -> ParseStatus:
        for player in match.players:
            if player.gold_t is not None:
                return ParseStatus.PARSED
        return ParseStatus.NOT_PARSED

    async def wait_for_parse(
        self,
        match_id: int,
        on_progress: Optional[Callable[[int, int], Awaitable[None]]] = None,
    ):
        await self.request_parse(match_id)
        for attempt in range(settings.parse_max_attempts):
            await asyncio.sleep(settings.parse_poll_interval)
            if on_progress is not None:
                await on_progress(attempt + 1, settings.parse_max_attempts)
            try:
                match = await self.fetch_match(match_id)
                status = self.detect_parse_status(match)
                if status == ParseStatus.PARSED:
                    return match, ParseStatus.PARSED
                logger.info(f"Parse attempt {attempt + 1}/{settings.parse_max_attempts}")
            except Exception as e:
                logger.warning(f"Poll error: {e}")
        match = await self.fetch_match(match_id)
        return match, ParseStatus.FAILED

    async def fetch_heroes(self) -> Dict[int, str]:
        data = await self._get("/heroes")
        return {hero["id"]: hero.get("localized_name", f"Hero#{hero['id']}") for hero in data}

    async def fetch_items(self) -> Dict[int, str]:
        data = await self._get("/constants/items")
        result = {}
        for key, val in data.items():
            item_id = val.get("id")
            if item_id is not None:
                result[item_id] = key
        return result

    async def fetch_player(self, account_id: int) -> dict:
        data = await self._get(f"/players/{int(account_id)}")
        if not isinstance(data, dict):
            raise OpenDotaAPIError("玩家数据格式无法识别")
        return data

    async def fetch_player_matches(
        self, account_id: int, limit: int = 8
    ) -> list:
        limit = max(1, min(int(limit), 50))
        data = await self._get(
            f"/players/{int(account_id)}/matches?limit={limit}"
        )
        if not isinstance(data, list):
            return []
        return data


_client: Optional[OpenDotaClient] = None


def get_client() -> OpenDotaClient:
    global _client
    if _client is None:
        _client = OpenDotaClient()
    return _client
