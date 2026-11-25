"""Unified LLM transport: OpenAI-compatible chat completions + Anthropic messages."""

import asyncio
import hashlib
import logging
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from app.services.llm_settings import LLMConfig

logger = logging.getLogger(__name__)


class LLMError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.retryable = retryable


def resolve_protocol(config: LLMConfig) -> str:
    if config.protocol in ("openai", "anthropic"):
        return config.protocol

    model = config.model.lower()
    base = config.base_url.lower()
    if "anthropic.com" in base:
        return "anthropic"
    if "opencode.ai" in base:
        # OpenCode Go routes most models through chat completions, but the
        # Claude / Qwen families and the original MiniMax M2/M3 ids use the
        # Anthropic Messages endpoint.
        if model.startswith(("claude", "qwen")):
            return "anthropic"
        if model in {"minimax-m3", "minimax-m2.7", "minimax-m2.5"}:
            return "anthropic"
    return "openai"


def new_session_id(seed: str) -> str:
    """Stable, opaque conversation id required by the OpenCode Go gateway."""
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]
    return f"ses_{digest}"


def _base_with_version(base_url: str, protocol: str) -> str:
    base = (base_url or "").rstrip("/")
    path = urlparse(base).path.rstrip("/")
    if protocol == "anthropic":
        if "/messages" in path:
            return base
        if not path.endswith("/v1"):
            base += "/v1"
        return base
    if not path:
        base += "/v1"
    return base


def _chat_endpoint(config: LLMConfig, protocol: str) -> str:
    base = (config.base_url or "").rstrip("/")
    suffix = "/messages" if protocol == "anthropic" else "/chat/completions"
    if base.endswith(suffix):
        return base
    return _base_with_version(base, protocol) + suffix


def _models_endpoint(config: LLMConfig, protocol: str) -> str:
    base = (config.base_url or "").rstrip("/")
    if base.endswith("/models"):
        return base
    return _base_with_version(base, protocol) + "/models"


def _auth_headers(
    config: LLMConfig, protocol: str, session_id: Optional[str] = None
) -> Dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "dota-review-assistant/2.0",
    }
    if "opencode.ai" in config.base_url.lower() and session_id:
        headers["x-opencode-session"] = session_id
    if not config.api_key:
        return headers
    if protocol == "anthropic":
        headers["x-api-key"] = config.api_key
        headers["anthropic-version"] = "2023-06-01"
    else:
        headers["Authorization"] = f"Bearer {config.api_key}"
    return headers


def _extract_error(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except Exception:
        return (resp.text or "").strip()[:400]

    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("type") or error)[:400]
        if isinstance(error, str):
            return error[:400]
        detail = data.get("detail")
        if detail:
            return str(detail)[:400]
        message = data.get("message")
        if message:
            return str(message)[:400]
    return (resp.text or "").strip()[:400]


def _friendly_http_error(status: int, detail: str) -> LLMError:
    if status == 401:
        return LLMError("API Key 无效或已过期（401）" + (f"：{detail}" if detail else ""), status_code=401)
    if status == 403:
        return LLMError("该 API Key 没有访问此模型的权限（403）" + (f"：{detail}" if detail else ""), status_code=403)
    if status == 404:
        return LLMError(
            "接口或模型不存在（404）。请检查 Base URL 是否以 /v1 结尾、模型 ID 是否正确"
            + (f"：{detail}" if detail else ""),
            status_code=404,
        )
    if status == 429:
        return LLMError("请求过于频繁或额度已用尽（429）" + (f"：{detail}" if detail else ""), status_code=429, retryable=True)
    if status >= 500:
        return LLMError(f"模型服务暂时不可用（{status}）" + (f"：{detail}" if detail else ""), status_code=status, retryable=True)
    return LLMError(f"模型接口返回错误（{status}）" + (f"：{detail}" if detail else ""), status_code=status)


def _join_openai_content(message: Dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return "".join(parts).strip()
    reasoning = message.get("reasoning_content")
    if isinstance(reasoning, str):
        return reasoning.strip()
    return ""


def _join_anthropic_content(data: Dict[str, Any]) -> str:
    blocks = data.get("content")
    if isinstance(blocks, str):
        return blocks.strip()
    if isinstance(blocks, list):
        parts = []
        for block in blocks:
            if isinstance(block, dict) and block.get("type") in (None, "text"):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return "".join(parts).strip()
    return ""


async def _post_chat(
    config: LLMConfig,
    protocol: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    temperature: float,
    timeout: float,
    session_id: Optional[str] = None,
) -> str:
    url = _chat_endpoint(config, protocol)
    headers = _auth_headers(config, protocol, session_id)

    if protocol == "anthropic":
        payload: Dict[str, Any] = {
            "model": config.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
    else:
        payload = {
            "model": config.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

    last_resp = None
    for _ in range(3):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15.0)) as client:
                resp = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMError(f"请求模型超时（{int(timeout)} 秒）：{exc}", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"无法连接模型服务：{exc}") from exc

        last_resp = resp
        if resp.status_code != 400 or protocol != "openai":
            break

        # Some providers (notably OpenAI reasoning models) renamed or dropped
        # legacy parameters. Adjust once and retry instead of failing outright.
        detail = _extract_error(resp)
        lower = detail.lower()
        if (
            "max_tokens" in payload
            and (
                "max_completion_tokens" in lower
                or ("max_tokens" in lower and any(word in lower for word in ("unsupported", "not supported", "invalid")))
            )
        ):
            payload["max_completion_tokens"] = payload.pop("max_tokens")
            continue
        if "temperature" in payload and any(
            phrase in lower
            for phrase in (
                "temperature does not support",
                "temperature is not supported",
                "unsupported parameter: 'temperature'",
                "unsupported value: 'temperature'",
            )
        ):
            payload.pop("temperature", None)
            continue
        break

    resp = last_resp
    if resp is None:
        raise LLMError("模型请求失败")
    if resp.status_code >= 400:
        raise _friendly_http_error(resp.status_code, _extract_error(resp))

    try:
        data = resp.json()
    except Exception as exc:
        raise LLMError("模型返回的不是合法 JSON") from exc

    finish_reason = None
    if protocol == "anthropic":
        text = _join_anthropic_content(data)
        finish_reason = data.get("stop_reason")
    else:
        choices = data.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            text = _join_openai_content(message)
            if not text:
                text = (choices[0].get("text") or "").strip()
            finish_reason = choices[0].get("finish_reason")
        else:
            text = ""

    if not text and finish_reason in {"length", "max_tokens"}:
        raise LLMError(
            "模型输出被 max_tokens 截断，没有返回正文。"
            "请在「模型设置」中调高最大输出 tokens，或换用非推理模型。"
        )
    if not text:
        raise LLMError("模型没有返回任何内容，请检查模型是否支持 Chat Completions 协议")
    return text


async def chat_completion(
    config: LLMConfig,
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    timeout: Optional[float] = None,
    retries: int = 2,
    session_id: Optional[str] = None,
) -> str:
    if not config.base_url:
        raise LLMError("尚未配置 Base URL")
    if not config.model:
        raise LLMError("尚未配置模型名称")
    if config.requires_key and not config.api_key:
        raise LLMError("尚未配置 API Key，请在「模型设置」中填写")

    protocol = resolve_protocol(config)
    max_tokens = max_tokens or config.max_tokens
    temperature = config.temperature if temperature is None else temperature
    timeout = timeout or config.timeout

    last_error: Optional[LLMError] = None
    for attempt in range(retries + 1):
        try:
            return await _post_chat(
                config,
                protocol,
                system_prompt,
                user_prompt,
                max_tokens,
                temperature,
                timeout,
                session_id,
            )
        except LLMError as exc:
            last_error = exc
            if not exc.retryable or attempt >= retries:
                raise
            wait = 2 ** attempt
            logger.warning(
                "LLM request failed (%s), retrying in %ss: %s",
                config.model,
                wait,
                exc.message,
            )
            await asyncio.sleep(wait)

    raise last_error or LLMError("模型请求失败")


async def list_models(
    config: LLMConfig, timeout: float = 20.0
) -> Tuple[List[Dict[str, str]], int]:
    if not config.base_url:
        raise LLMError("尚未配置 Base URL")

    protocol = resolve_protocol(config)
    url = _models_endpoint(config, protocol)
    headers = _auth_headers(config, protocol)
    headers.pop("Content-Type", None)

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0)) as client:
            resp = await client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        raise LLMError("获取模型列表超时，请手动输入模型 ID") from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"无法连接模型服务：{exc}") from exc

    if resp.status_code >= 400:
        raise _friendly_http_error(resp.status_code, _extract_error(resp))

    try:
        payload = resp.json()
    except Exception as exc:
        raise LLMError("模型列表接口返回的不是 JSON") from exc

    items = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise LLMError("模型列表格式无法识别")

    models: List[Dict[str, str]] = []
    seen = set()
    skipped = 0
    for item in items:
        protocol = "auto"
        if isinstance(item, str):
            model_id = item.strip()
            name = model_id
        elif isinstance(item, dict):
            model_id = str(item.get("id") or item.get("model") or item.get("name") or "").strip()
            name = str(item.get("name") or item.get("display_name") or model_id).strip()

            model_type = str(item.get("type") or "").lower()
            if model_type and model_type not in {"chat", "model"}:
                skipped += 1
                continue

            api = item.get("api")
            if isinstance(api, dict) and api:
                if "messages" in api:
                    protocol = "anthropic"
                else:
                    # OpenCode Go translates native Responses / Gemini models to
                    # chat completions, which is the transport this app uses.
                    protocol = "openai"
        else:
            continue
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        models.append({"id": model_id, "name": name, "protocol": protocol})

    return models, skipped


async def test_connection(config: LLMConfig) -> Dict[str, Any]:
    if not config.base_url or not config.model:
        raise LLMError("请先填写 Base URL 与模型名称")
    if config.requires_key and not config.api_key:
        raise LLMError("请先填写 API Key")

    started = time.perf_counter()
    reply = await chat_completion(
        config,
        "你是连通性测试助手，只回复用户要求的内容。",
        "请只回复两个字符：OK",
        max_tokens=16,
        temperature=0,
        timeout=min(config.timeout, 60),
        retries=0,
        session_id=new_session_id(f"connect-test:{time.time_ns()}"),
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    return {
        "ok": True,
        "latency_ms": latency_ms,
        "reply": reply[:200],
        "model": config.model,
        "protocol": resolve_protocol(config),
    }
