"""API schemas. `AgentConfig` is the contract shared with the voice worker.

Everything an agent needs at call time lives here, so creating or changing an
agent is a UI/database operation, never a code change. Secrets (API keys) are
NOT stored here; the worker reads them from its own env.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Tools the worker knows how to run. Agents pick a subset.
TOOL_CATALOG: dict[str, str] = {
    "hangup": "End the call politely.",
    "transfer_to_human": "Escalate to a human (logged; warm transfer once telephony is wired).",
    "log_complaint": "Record a complaint, hardship or follow-up note.",
    "log_payment_promise": "Record a promise-to-pay (date + amount).",
    "create_payment_request": "Create a payment link and send it by SMS/app.",
}

LLM_PROVIDERS = ("google", "groq", "openai", "cerebras")


class VoiceConfig(BaseModel):
    provider: Literal["cartesia"] = "cartesia"
    voice_id: str = "f786b574-daa5-4673-aa0c-cbe3e8534c02"
    language: str = "hi"
    speed: float = Field(1.1, ge=0.6, le=1.5)


Provider = Literal["google", "groq", "openai", "cerebras"]


class LLMSpec(BaseModel):
    provider: Provider
    model: str = Field(..., min_length=2)
    reasoning_effort: str = ""


class LLMConfig(BaseModel):
    provider: Provider = "groq"
    model: str = "qwen/qwen3.8-27b"
    temperature: float = Field(0.4, ge=0, le=1.5)
    reasoning_effort: str = "none"  # groq qwen: none; gpt-oss: low; ignored by google
    # Tried in order when the primary errors or hangs. Use other providers: one outage shouldn't take all.
    fallbacks: list[LLMSpec] = Field(default_factory=lambda: [LLMSpec(provider="google", model="gemini-3.5-flash")],
                                     max_length=3)

    @model_validator(mode="before")
    @classmethod
    def _migrate_fallback_model(cls, data: Any) -> Any:
        """Configs saved before multi-provider fallbacks had `fallback_model: str` (Gemini)."""
        if isinstance(data, dict) and "fallback_model" in data and "fallbacks" not in data:
            data = dict(data)
            fm = data.pop("fallback_model")
            data["fallbacks"] = [{"provider": "google", "model": fm}] if fm else []
        return data


class STTConfig(BaseModel):
    provider: Literal["deepgram"] = "deepgram"
    model: str = "nova-3"
    language: str = "hi"


class TurnConfig(BaseModel):
    """Optional overrides of the worker's latency defaults (None = keep worker default)."""

    endpoint_min_delay: float | None = Field(None, ge=0.1, le=3)
    endpoint_max_delay: float | None = Field(None, ge=0.5, le=6)
    interrupt_min_duration: float | None = Field(None, ge=0.1, le=3)
    interrupt_min_words: int | None = Field(None, ge=0, le=5)
    preemptive_generation: bool | None = None


class SafetyConfig(BaseModel):
    max_call_seconds: int = Field(360, ge=30, le=1800)
    user_away_timeout: float = Field(12, ge=4, le=60)
    max_inactivity_prompts: int = Field(2, ge=0, le=5)


class DispositionQuestion(BaseModel):
    id: str
    question: str
    type: Literal["enum", "bool", "text"]
    choices: list[str] = []

    @field_validator("id")
    @classmethod
    def _snake(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,40}", v):
            raise ValueError("id must be snake_case, e.g. call_outcome")
        return v

    @model_validator(mode="after")
    def _choices(self) -> DispositionQuestion:
        if self.type == "enum" and len(self.choices) < 2:
            raise ValueError(f"enum question '{self.id}' needs at least 2 choices")
        return self


class AgentConfig(BaseModel):
    use_case: Literal["collections", "sales", "support", "other"] = "other"
    language: str = "Hinglish"
    persona_name: str = "Neha"
    opening_line: str = ""  # said straight to TTS, no LLM; may use {variables}
    prompt: str = Field(..., min_length=20)  # the script / instructions; may use {variables}
    variables: list[str] = []  # call-time values, e.g. driver_name, due_date
    tools: list[str] = ["hangup"]
    voice: VoiceConfig = VoiceConfig()
    llm: LLMConfig = LLMConfig()
    stt: STTConfig = STTConfig()
    turn: TurnConfig = TurnConfig()
    safety: SafetyConfig = SafetyConfig()
    dispositions: list[DispositionQuestion] = []

    @field_validator("tools")
    @classmethod
    def _known_tools(cls, v: list[str]) -> list[str]:
        unknown = sorted(set(v) - set(TOOL_CATALOG))
        if unknown:
            raise ValueError(f"unknown tools: {unknown}. Known: {sorted(TOOL_CATALOG)}")
        return sorted(set(v), key=v.index)

    @model_validator(mode="after")
    def _variables_declared(self) -> AgentConfig:
        used = set(re.findall(r"\{([a-z_][a-z0-9_]*)\}", self.prompt + " " + self.opening_line))
        missing = sorted(used - set(self.variables))
        if missing:
            raise ValueError(f"prompt uses undeclared variables {missing}; add them to `variables`")
        ids = [q.id for q in self.dispositions]
        if len(ids) != len(set(ids)):
            raise ValueError("disposition question ids must be unique")
        return self


# ── request / response models ─────────────────────────────────────────────────
class AgentCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    config: AgentConfig


class AgentUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=120)
    status: Literal["draft", "live", "paused", "archived"] | None = None
    config: AgentConfig | None = None


class AgentOut(BaseModel):
    id: str
    name: str
    status: str
    config: AgentConfig
    published_version: int | None
    created_at: datetime
    updated_at: datetime
    stats: dict[str, Any] = {}


class PublishIn(BaseModel):
    note: str = ""


class VersionOut(BaseModel):
    version: int
    note: str
    created_at: datetime
    config: AgentConfig


class RuntimeConfigOut(BaseModel):
    agent_id: str
    name: str
    version: int
    config: AgentConfig


class CallIn(BaseModel):
    """What the worker posts at the end of a call (and again when dispositions finish)."""

    id: str
    agent_id: str | None = None
    agent_version: int | None = None
    room_name: str
    started_at: datetime
    ended_at: datetime | None = None
    duration_s: float = 0
    ended_by: str = "unknown"
    context: dict[str, Any] = {}
    pipeline: dict[str, Any] = {}
    metrics: dict[str, Any] = {}
    dispositions: dict[str, Any] = {}
    tool_calls: list[dict[str, Any]] = []
    transcript: list[dict[str, Any]] = []


class CallSummary(BaseModel):
    id: str
    agent_id: str | None
    agent_version: int | None
    room_name: str
    started_at: datetime
    duration_s: float
    ended_by: str
    outcome: str | None
    response_p50_ms: float | None
    response_p95_ms: float | None
    llm_ttft_p50_ms: float | None
    cost_inr: float | None
    cost_inr_per_min: float | None
    interrupt_rate: float | None
    llm_failovers: int | None = None


class CallPage(BaseModel):
    items: list[CallSummary]
    total: int
    limit: int
    offset: int


class CallOut(CallSummary):
    context: dict[str, Any]
    pipeline: dict[str, Any]
    metrics: dict[str, Any]
    dispositions: dict[str, Any]
    tool_calls: list[dict[str, Any]]
    transcript: list[dict[str, Any]]
    redacted: bool = False  # true for public visitors: transcript and context removed


class TestSessionIn(BaseModel):
    version: int | None = None  # None = latest published, falls back to draft
    use_draft: bool = False
    context: dict[str, str] = {}


class TestSessionOut(BaseModel):
    livekit_url: str
    token: str
    room_name: str
    agent_version: int | None
