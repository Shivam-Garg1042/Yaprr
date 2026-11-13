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
    # Access token for the dashboard/API (Authorization: Bearer <token>). Empty = open (local dev only).
    # A public deploy without it lets anyone start calls on your LLM/TTS keys.
    admin_token: str = ""

    # Public read-only mode: visitors can browse agents, calls and dashboards without a token.
    # Writes still need ADMIN_TOKEN.
    public_read: bool = False
    # Visitors also see transcripts. The /try page tells callers their call will be public.
    public_transcripts: bool = True

    # Public "try it" demo: anyone can start a short call with one agent, within spend caps.
    demo_enabled: bool = False
    demo_agent_id: str = ""            # empty = the seeded collections demo agent
    demo_max_call_seconds: int = 120   # the worker hangs up at this point
    demo_calls_per_ip_per_day: int = 3
    demo_minutes_per_day: int = 60     # global cap; every call reserves its full max length up front


@lru_cache
def get_settings() -> Settings:
    return Settings()
