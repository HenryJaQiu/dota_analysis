from app.services.llm_client import resolve_protocol
from app.services.llm_settings import (
    LLMConfig,
    mask_api_key,
    provider_catalog,
    same_origin,
)


def test_opencode_go_defaults_are_present():
    catalog = {item["id"]: item for item in provider_catalog()}
    assert "opencode-go" in catalog
    assert catalog["opencode-go"]["default_model"] == "deepseek-v4.1-flash"
    assert catalog["opencode-go"]["base_url"] == "https://opencode.ai/zen/go/v1"


def test_protocol_auto_detection():
    opencode = "https://opencode.ai/zen/go/v1"
    assert resolve_protocol(LLMConfig(
        provider="opencode-go", base_url=opencode, model="deepseek-v4.1-flash"
    )) == "openai"
    assert resolve_protocol(LLMConfig(
        provider="opencode-go", base_url=opencode, model="minimax-m3"
    )) == "anthropic"
    assert resolve_protocol(LLMConfig(
        provider="opencode-go", base_url=opencode, model="minimax-m3.1-flash"
    )) == "openai"
    assert resolve_protocol(LLMConfig(
        provider="opencode-go", base_url=opencode, model="qwen3.7-max"
    )) == "anthropic"
    assert resolve_protocol(LLMConfig(
        provider="custom", base_url=opencode, model="deepseek-v4.1-flash", protocol="anthropic"
    )) == "anthropic"


def test_mask_api_key_never_returns_full_key():
    masked = mask_api_key("sk-1234567890abcdef")
    assert masked.startswith("sk-1")
    assert masked.endswith("cdef")
    assert "234567890abc" not in masked
    assert mask_api_key("short") == "*****"


def test_same_origin():
    assert same_origin("https://api.example.com/v1", "https://api.example.com/v2")
    assert not same_origin("https://api.example.com/v1", "https://evil.example.com/v1")
    assert not same_origin("http://localhost:11434/v1", "https://localhost:11434/v1")
