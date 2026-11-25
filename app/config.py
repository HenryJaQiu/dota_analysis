from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ===== AI / LLM =====
    # These values only seed the first-run configuration. After the first save,
    # everything can be edited in the web UI and is stored in llm_settings_file.
    llm_provider: str = "opencode-go"
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    llm_protocol: str = "auto"
    llm_temperature: float = 0.4
    llm_max_tokens: int = 4096
    llm_timeout: int = 180
    llm_concurrency: int = 3
    llm_settings_file: str = "cache/llm_settings.json"

    # Provider-specific keys, kept for backwards compatibility and first-run seeding.
    opencode_api_key: str = ""
    opencode_go_api_key: str = ""
    minimax_api_key: str = ""
    minimax_base_url: str = "https://api.minimax.chat/v1"
    minimax_model: str = "MiniMax-M2.7"
    deepseek_api_key: str = ""
    openai_api_key: str = ""

    # ===== Application =====
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    cache_dir: str = "cache/matches"
    raw_cache_dir: str = "cache/raw"
    # 0 = keep downloaded matches forever for later review.
    cache_ttl_seconds: int = 0
    opendota_base_url: str = "https://api.opendota.com/api"
    opendota_rate_limit: float = 1.0
    parse_poll_interval: int = 10
    parse_max_attempts: int = 30

    # ===== Followed players =====
    follows_file: str = "cache/follows.json"
    follows_refresh_seconds: int = 300
    follows_max: int = 20
    follows_match_limit: int = 8
    # Optional: used to resolve Steam vanity profile URLs.
    steam_api_key: str = ""


settings = Settings()
