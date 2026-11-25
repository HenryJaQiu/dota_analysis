import logging
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from app.services.llm_client import (
    LLMError,
    list_models,
    resolve_protocol,
    test_connection,
)
from app.services.llm_settings import (
    clear_api_key,
    config_for_request,
    get_llm_config,
    get_preset,
    public_settings,
    update_llm_config,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/llm", tags=["llm"])


class LLMSettingsPayload(BaseModel):
    provider: str = "opencode-go"
    base_url: str = ""
    api_key: Optional[str] = None
    model: str = ""
    protocol: Literal["auto", "openai", "anthropic"] = "auto"
    temperature: float = Field(0.4, ge=0.0, le=2.0)
    max_tokens: int = Field(4096, ge=64, le=32768)
    timeout: int = Field(180, ge=10, le=600)
    concurrency: int = Field(3, ge=1, le=10)

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        value = (value or "").strip().rstrip("/")
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("Base URL 必须以 http:// 或 https:// 开头")
        return value

    @field_validator("model")
    @classmethod
    def _validate_model(cls, value: str) -> str:
        return (value or "").strip()


class LLMTestPayload(BaseModel):
    provider: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    protocol: Optional[Literal["auto", "openai", "anthropic"]] = None


@router.get("/settings")
async def read_settings() -> Dict[str, Any]:
    return public_settings()


@router.put("/settings")
async def save_settings(payload: LLMSettingsPayload) -> Dict[str, Any]:
    try:
        update_llm_config(payload.model_dump())
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return public_settings()


@router.post("/settings/clear-key")
async def remove_api_key() -> Dict[str, Any]:
    clear_api_key()
    return public_settings()


@router.get("/models")
async def discover_models(
    base_url: str = Query(""),
    api_key: str = Query(""),
    protocol: str = Query(""),
    provider: str = Query(""),
) -> Dict[str, Any]:
    config = config_for_request(
        base_url=base_url,
        api_key=api_key,
        protocol=protocol,
        provider=provider,
    )
    if not config.base_url:
        raise HTTPException(status_code=400, detail="请先填写 Base URL")

    try:
        models, skipped = await list_models(config)
        return {
            "models": models,
            "skipped": skipped,
            "source": "remote",
            "warning": None,
            "resolved_protocol": resolve_protocol(config),
            "base_url": config.base_url,
        }
    except LLMError as exc:
        fallback = [
            {"id": model_id, "name": model_id, "protocol": "auto"}
            for model_id in get_preset(config.provider).get("fallback_models", [])
        ]
        if fallback:
            return {
                "models": fallback,
                "source": "preset",
                "warning": f"{exc.message}。已显示预设模型列表，可直接手动输入模型 ID。",
                "resolved_protocol": resolve_protocol(config),
                "base_url": config.base_url,
            }
        raise HTTPException(status_code=502, detail=exc.message) from exc


@router.post("/test")
async def test_model(payload: LLMTestPayload) -> Dict[str, Any]:
    stored = get_llm_config()
    config = config_for_request(
        base_url=payload.base_url or "",
        api_key=payload.api_key or "",
        model=payload.model or "",
        protocol=payload.protocol or "",
        provider=payload.provider or stored.provider,
    )
    if not config.base_url or not config.model:
        raise HTTPException(status_code=400, detail="请先填写 Base URL 与模型名称")
    if config.requires_key and not config.api_key:
        raise HTTPException(status_code=400, detail="请先填写 API Key")

    try:
        result = await test_connection(config)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=exc.message) from exc
    except Exception as exc:
        logger.exception("LLM connection test crashed")
        raise HTTPException(status_code=500, detail=f"测试失败：{str(exc)[:200]}") from exc
    return result
