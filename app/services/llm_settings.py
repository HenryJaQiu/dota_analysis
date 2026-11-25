"""Persistent, provider-agnostic LLM configuration for the review assistant."""

import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.config import settings

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "opencode-go"
PROTOCOLS = ("auto", "openai", "anthropic")

OPENCODE_GO_MODELS = [
    "deepseek-v4.1-flash",
    "deepseek-v4-pro",
    "glm-5.3",
    "glm-5.3-flash",
    "grok-4.7",
    "muse-spark-1.2-contributor",
    "muse-spark-1.3-contributor",
    "gpt-5.6-luna",
    "gpt-6-luna",
    "claude-haiku-5-5",
    "hy3",
    "hy4-preview",
    "hy4",
    "hy4-flash-free",
    "kimi-k2.7-code",
    "kimi-k3",
    "kimi-k3.1-pro",
    "mimo-v2.6-flash",
    "mimo-v2.6-pro",
    "minimax-m3",
    "minimax-m3.1-flash",
    "step-5-preview",
    "beam-free",
    "qwen3.8-max",
    "qwen3.8-flash",
    "qwen3.7-plus",
    "qwen4-max",
    "gemini-4-argon",
    "longcat-2.5",
    "iceman-contributor-free",
    "hungerg-free",
]

PROVIDER_PRESETS: Dict[str, Dict[str, Any]] = {
    "opencode-go": {
        "label": "OpenCode Go",
        "base_url": "https://opencode.ai/zen/go/v1",
        "default_model": "deepseek-v4.1-flash",
        "protocol": "auto",
        "requires_key": True,
        "key_hint": "在 opencode.ai/auth 订阅后获取 API Key（OPENCODE_API_KEY）",
        "docs_url": "https://opencode.ai/auth",
        "description": "OpenCode Go 订阅。DeepSeek / Kimi / GLM 走 OpenAI 协议，MiniMax / Qwen 自动走 Anthropic 协议。",
        "fallback_models": OPENCODE_GO_MODELS,
    },
    "deepseek": {
        "label": "DeepSeek 官方",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "protocol": "openai",
        "requires_key": True,
        "key_hint": "在 platform.deepseek.com 创建 API Key",
        "docs_url": "https://platform.deepseek.com/api_keys",
        "description": "DeepSeek 官方 OpenAI 兼容接口。",
        "fallback_models": ["deepseek-chat", "deepseek-reasoner"],
    },
    "minimax": {
        "label": "MiniMax",
        "base_url": "https://api.minimax.chat/v1",
        "default_model": "MiniMax-M2.7",
        "protocol": "openai",
        "requires_key": True,
        "key_hint": "在 MiniMax 开放平台创建 API Key（MINIMAX_API_KEY）",
        "docs_url": "https://platform.minimaxi.com/",
        "description": "MiniMax 兼容 OpenAI 的接口，原项目默认使用此来源。",
        "fallback_models": ["MiniMax-M2.7", "MiniMax-M2.5", "MiniMax-M3"],
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4.1-mini",
        "protocol": "openai",
        "requires_key": True,
        "key_hint": "sk- 开头的 OpenAI API Key",
        "docs_url": "https://platform.openai.com/api-keys",
        "description": "OpenAI 官方接口，也可在此填入 OpenAI 兼容网关地址。",
        "fallback_models": ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini", "gpt-4o"],
    },
    "ollama": {
        "label": "Ollama / 本地服务",
        "base_url": "http://127.0.0.1:11434/v1",
        "default_model": "qwen3:8b",
        "protocol": "openai",
        "requires_key": False,
        "key_hint": "本地服务通常不需要 Key，留空即可",
        "docs_url": "https://ollama.com/",
        "description": "Ollama、LM Studio、vLLM 等本地 OpenAI 兼容服务。",
        "fallback_models": [],
    },
    "custom": {
        "label": "自定义兼容接口",
        "base_url": "",
        "default_model": "",
        "protocol": "auto",
        "requires_key": False,
        "key_hint": "如果服务需要鉴权请填写；本地服务可留空",
        "docs_url": "",
        "description": "任何 OpenAI / Anthropic 兼容端点，例如自建网关或中转站。",
        "fallback_models": [],
    },
}

_PROVIDER_ORDER = ["opencode-go", "deepseek", "minimax", "openai", "ollama", "custom"]


@dataclass
class LLMConfig:
    provider: str
    base_url: str
    model: str
    api_key: str = ""
    protocol: str = "auto"
    temperature: float = 0.4
    max_tokens: int = 4096
    timeout: int = 180
    concurrency: int = 3

    @property
    def preset(self) -> Dict[str, Any]:
        return PROVIDER_PRESETS.get(self.provider, PROVIDER_PRESETS["custom"])

    @property
    def provider_label(self) -> str:
        return self.preset["label"]

    @property
    def requires_key(self) -> bool:
        return bool(self.preset.get("requires_key", False))

    @property
    def configured(self) -> bool:
        if not self.base_url or not self.model:
            return False
        return bool(self.api_key) or not self.requires_key

    def public_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "provider_label": self.provider_label,
            "base_url": self.base_url,
            "model": self.model,
            "protocol": self.protocol,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "concurrency": self.concurrency,
            "api_key_set": bool(self.api_key),
            "api_key_masked": mask_api_key(self.api_key),
            "requires_key": self.requires_key,
            "configured": self.configured,
        }


_lock = threading.RLock()
_config: Optional[LLMConfig] = None


def mask_api_key(key: str) -> str:
    key = (key or "").strip()
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}…{key[-4:]}"


def provider_catalog() -> List[Dict[str, Any]]:
    items = []
    for provider_id in _PROVIDER_ORDER:
        preset = PROVIDER_PRESETS[provider_id]
        items.append({
            "id": provider_id,
            "label": preset["label"],
            "base_url": preset["base_url"],
            "default_model": preset["default_model"],
            "protocol": preset["protocol"],
            "requires_key": preset["requires_key"],
            "key_hint": preset["key_hint"],
            "docs_url": preset["docs_url"],
            "description": preset["description"],
            "fallback_models": list(preset["fallback_models"]),
        })
    return items


def get_preset(provider: str) -> Dict[str, Any]:
    return PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["custom"])


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _seed_api_key(provider: str) -> str:
    return {
        "opencode-go": settings.opencode_api_key or settings.opencode_go_api_key,
        "minimax": settings.minimax_api_key,
        "deepseek": settings.deepseek_api_key,
        "openai": settings.openai_api_key,
    }.get(provider, "")


def _seed_from_env() -> LLMConfig:
    provider = (settings.llm_provider or DEFAULT_PROVIDER).strip() or DEFAULT_PROVIDER

    # Backwards compatibility: an existing MiniMax-only .env keeps working when
    # the user did not explicitly pick a provider.
    if (
        not os.getenv("LLM_PROVIDER")
        and settings.minimax_api_key
        and not (settings.opencode_api_key or settings.opencode_go_api_key or settings.llm_api_key)
    ):
        provider = "minimax"

    if provider not in PROVIDER_PRESETS:
        provider = "custom"

    preset = get_preset(provider)
    base_url = (settings.llm_base_url or preset["base_url"]).strip().rstrip("/")
    model = (settings.llm_model or "").strip()
    if not model:
        if provider == "minimax" and settings.minimax_model:
            model = settings.minimax_model.strip()
        else:
            model = preset["default_model"]

    return LLMConfig(
        provider=provider,
        base_url=base_url,
        model=model,
        api_key=(settings.llm_api_key or _seed_api_key(provider)).strip(),
        protocol=_normalize_protocol(settings.llm_protocol),
        temperature=_clamp(settings.llm_temperature, 0.0, 2.0),
        max_tokens=int(_clamp(settings.llm_max_tokens, 64, 32768)),
        timeout=int(_clamp(settings.llm_timeout, 10, 600)),
        concurrency=int(_clamp(settings.llm_concurrency, 1, 10)),
    )


def _normalize_protocol(value: Optional[str]) -> str:
    value = (value or "auto").strip().lower()
    return value if value in PROTOCOLS else "auto"


def _normalize_config(data: Dict[str, Any]) -> LLMConfig:
    provider = str(data.get("provider") or DEFAULT_PROVIDER).strip()
    if provider not in PROVIDER_PRESETS:
        provider = "custom"

    preset = get_preset(provider)
    base_url = str(data.get("base_url") or preset["base_url"]).strip().rstrip("/")
    model = str(data.get("model") or preset["default_model"]).strip()
    if not base_url:
        raise ValueError("Base URL 不能为空")
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("Base URL 必须以 http:// 或 https:// 开头")
    if not model:
        raise ValueError("模型名称不能为空")

    return LLMConfig(
        provider=provider,
        base_url=base_url,
        model=model,
        api_key=str(data.get("api_key") or "").strip(),
        protocol=_normalize_protocol(data.get("protocol")),
        temperature=_clamp(float(data.get("temperature", 0.4)), 0.0, 2.0),
        max_tokens=int(_clamp(int(data.get("max_tokens", 4096)), 64, 32768)),
        timeout=int(_clamp(int(data.get("timeout", 180)), 10, 600)),
        concurrency=int(_clamp(int(data.get("concurrency", 3)), 1, 10)),
    )


def _settings_path() -> str:
    return settings.llm_settings_file


def _load_from_disk() -> Optional[Dict[str, Any]]:
    path = _settings_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return data
    except Exception as exc:
        logger.warning("Could not read LLM settings from %s: %s", path, exc)
        return None


def _write_to_disk(config: LLMConfig) -> None:
    path = _settings_path()
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    payload = {
        "version": 1,
        "provider": config.provider,
        "base_url": config.base_url,
        "model": config.model,
        "api_key": config.api_key,
        "protocol": config.protocol,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "timeout": config.timeout,
        "concurrency": config.concurrency,
    }
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def get_llm_config() -> LLMConfig:
    global _config
    with _lock:
        if _config is None:
            stored = _load_from_disk()
            if stored:
                merged = _seed_from_env()
                merged = LLMConfig(
                    provider=str(stored.get("provider") or merged.provider),
                    base_url=str(stored.get("base_url") or merged.base_url),
                    model=str(stored.get("model") or merged.model),
                    api_key=str(stored.get("api_key") or ""),
                    protocol=_normalize_protocol(stored.get("protocol", merged.protocol)),
                    temperature=_clamp(float(stored.get("temperature", merged.temperature)), 0.0, 2.0),
                    max_tokens=int(_clamp(int(stored.get("max_tokens", merged.max_tokens)), 64, 32768)),
                    timeout=int(_clamp(int(stored.get("timeout", merged.timeout)), 10, 600)),
                    concurrency=int(_clamp(int(stored.get("concurrency", merged.concurrency)), 1, 10)),
                )
                if merged.provider not in PROVIDER_PRESETS:
                    merged.provider = "custom"
                _config = merged
            else:
                _config = _seed_from_env()
        return _config


def public_settings() -> Dict[str, Any]:
    data = get_llm_config().public_dict()
    data["providers"] = provider_catalog()
    data["settings_file"] = _settings_path()
    return data


def update_llm_config(data: Dict[str, Any]) -> LLMConfig:
    global _config
    with _lock:
        current = get_llm_config()
        provider = str(data.get("provider") or current.provider).strip()
        if provider not in PROVIDER_PRESETS:
            provider = "custom"

        raw_key = data.get("api_key", None)
        if raw_key is None:
            api_key = current.api_key if provider == current.provider else ""
        else:
            supplied = str(raw_key).strip()
            if supplied:
                api_key = supplied
            else:
                api_key = current.api_key if provider == current.provider else ""

        merged = {
            "provider": provider,
            "base_url": data.get("base_url", current.base_url),
            "model": data.get("model", current.model),
            "api_key": api_key,
            "protocol": data.get("protocol", current.protocol),
            "temperature": data.get("temperature", current.temperature),
            "max_tokens": data.get("max_tokens", current.max_tokens),
            "timeout": data.get("timeout", current.timeout),
            "concurrency": data.get("concurrency", current.concurrency),
        }
        config = _normalize_config(merged)
        _write_to_disk(config)
        _config = config
        logger.info(
            "LLM settings updated: provider=%s model=%s base_url=%s key_set=%s",
            config.provider,
            config.model,
            config.base_url,
            bool(config.api_key),
        )
        return config


def clear_api_key() -> LLMConfig:
    global _config
    with _lock:
        current = get_llm_config()
        config = LLMConfig(
            provider=current.provider,
            base_url=current.base_url,
            model=current.model,
            api_key="",
            protocol=current.protocol,
            temperature=current.temperature,
            max_tokens=current.max_tokens,
            timeout=current.timeout,
            concurrency=current.concurrency,
        )
        _write_to_disk(config)
        _config = config
        return config


def same_origin(url_a: str, url_b: str) -> bool:
    try:
        a = urlparse(url_a)
        b = urlparse(url_b)
        return (a.scheme, a.netloc) == (b.scheme, b.netloc)
    except Exception:
        return False


def config_for_request(
    *,
    base_url: str = "",
    api_key: str = "",
    model: str = "",
    protocol: str = "",
    provider: str = "",
) -> LLMConfig:
    """Build a temporary config for discovery / connection tests.

    A stored API key is only reused when the requested endpoint shares the same
    origin as the saved endpoint, so a crafted request cannot redirect the key
    to a third-party host.
    """

    stored = get_llm_config()
    provider = (provider or stored.provider).strip()
    if provider not in PROVIDER_PRESETS:
        provider = "custom"
    preset = get_preset(provider)

    target_base = (base_url or stored.base_url or preset["base_url"]).strip().rstrip("/")
    target_model = (model or stored.model or preset["default_model"]).strip()
    target_protocol = _normalize_protocol(protocol or stored.protocol)

    target_key = (api_key or "").strip()
    if not target_key and stored.api_key and same_origin(target_base, stored.base_url):
        target_key = stored.api_key

    return LLMConfig(
        provider=provider,
        base_url=target_base,
        model=target_model,
        api_key=target_key,
        protocol=target_protocol,
        temperature=stored.temperature,
        max_tokens=stored.max_tokens,
        timeout=stored.timeout,
        concurrency=stored.concurrency,
    )
