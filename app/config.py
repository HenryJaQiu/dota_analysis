import os
from pydantic import BaseSettings


class Settings(BaseSettings):
    minimax_api_key: str = ""
    minimax_base_url: str = "https://api.minimax.chat/v1"
    minimax_model: str = "MiniMax-M2.7"
    cache_dir: str = "cache/matches"
    cache_ttl_seconds: int = 86400
    opendota_base_url: str = "https://api.opendota.com/api"
    opendota_rate_limit: float = 1.0
    parse_poll_interval: int = 10
    parse_max_attempts: int = 12
    ai_max_tokens: int = 4096

    class Config:
        env_file = ".env"


settings = Settings()
