import asyncio
import json

from services.config import AppConfig
from services.runtime import apply_agent_overrides, parse_job_metadata, resolve_agent


def _base(**kw):
    return AppConfig(livekit_url="x", livekit_api_key="x", livekit_api_secret="x", deepgram_api_key="x",
                     google_api_key="x", cartesia_api_key="x", **kw)


def test_parse_job_metadata_tolerates_garbage():
    assert parse_job_metadata("") == {} and parse_job_metadata("not json") == {} and parse_job_metadata("[1]") == {}
    assert parse_job_metadata('{"agent_id": "a1"}') == {"agent_id": "a1"}


def test_agent_overrides_env_defaults_only_where_set():
    base = _base(llm_provider="openai", llm_base_url="https://env-url", llm_api_key="env-key")
    cfg = {"llm": {"provider": "groq", "model": "qwen/qwen3.8-27b", "temperature": 0.3, "reasoning_effort": "none",
                   "fallbacks": [{"provider": "openai", "model": "gpt-4.1-mini"}, {"provider": "google", "model": "gemini-3.5-flash"}]},
           "voice": {"voice_id": "v2", "speed": 1.2, "language": "hi"},
           "stt": {"model": "nova-3", "language": "hi"},
           "turn": {"endpoint_min_delay": 0.3, "interrupt_min_words": None},
           "safety": {"max_call_seconds": 120}}
    out = apply_agent_overrides(base, cfg)
    assert (out.llm_provider, out.llm_model, out.llm_temperature) == ("groq", "qwen/qwen3.8-27b", 0.3)
    assert out.llm_base_url == "" and out.llm_api_key == ""  # env URL/key were for another provider
    assert (out.tts_voice, out.tts_speed, out.stt_language) == ("v2", 1.2, "hi")
    assert out.turn.endpoint_min_delay == 0.3 and out.turn.interrupt_min_words == base.turn.interrupt_min_words
    assert out.safety.max_call_seconds == 120 and out.safety.user_away_timeout == base.safety.user_away_timeout
    assert [(f.provider, f.model) for f in out.llm_fallbacks] == [("openai", "gpt-4.1-mini"), ("google", "gemini-3.5-flash")]
    assert base.llm_provider == "openai"  # original untouched
    legacy = apply_agent_overrides(base, {"llm": {"provider": "groq", "model": "m", "fallback_model": "gemini-x"}})
    assert [(f.provider, f.model) for f in legacy.llm_fallbacks] == [("google", "gemini-x")]


def test_resolve_falls_back_to_local_demo_without_api(monkeypatch):
    monkeypatch.delenv("YAPRR_API_URL", raising=False)
    meta = json.dumps({"agent_id": "abc", "context": {"customer_name": "Shivam"}})
    r = asyncio.run(resolve_agent(meta))
    assert r.source == "local" and r.config["prompt"]
    assert r.context["customer_name"] == "Shivam" and r.context["scenario"]  # job context overrides demo context
