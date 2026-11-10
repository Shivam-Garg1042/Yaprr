from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """API settings, read from env / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://yaprr:yaprr@localhost:5432/yaprr"
    # Shared secret the voice worker sends in `X-Worker-Token` (runtime config + call ingest).
    worker_token: str = "dev-worker-token"
    cors_origins: str = "http://localhost:5173"

    # LiveKit, for "Talk to agent" test sessions from the browser.
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    worker_agent_name: str = "yaprr-agent"  # must match the worker's WorkerOptions(agent_name=...)

    seed_demo_agents: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
