import logging

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.services.follows import (
    FollowError,
    add_follow,
    list_follows,
    refresh_follows,
    remove_follow,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/follows", tags=["follows"])


class FollowCreate(BaseModel):
    steam_id: str = Field(..., min_length=1, max_length=200)
    nickname: str = Field("", max_length=32)


def _error(exc: FollowError) -> JSONResponse:
    return JSONResponse({"error": exc.message}, status_code=exc.status_code)


@router.get("")
async def get_follows():
    return JSONResponse(list_follows())


@router.post("")
async def create_follow(payload: FollowCreate):
    try:
        added = await add_follow(payload.steam_id, payload.nickname)
    except FollowError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("Could not add followed player")
        return JSONResponse(
            {"error": f"关注失败：{str(exc)[:200]}"},
            status_code=500,
        )

    data = list_follows()
    data["added"] = added
    return JSONResponse(data)


@router.delete("/{account_id}")
async def delete_follow(account_id: int):
    try:
        remove_follow(account_id)
    except FollowError as exc:
        return _error(exc)
    return JSONResponse(list_follows())


@router.post("/refresh")
async def refresh(force: bool = Query(False)):
    try:
        return JSONResponse(await refresh_follows(force=force))
    except FollowError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("Could not refresh followed players")
        return JSONResponse(
            {"error": f"刷新失败：{str(exc)[:200]}"},
            status_code=500,
        )
