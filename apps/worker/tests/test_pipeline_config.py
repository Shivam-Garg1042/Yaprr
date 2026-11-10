from services.config import AppConfig, load_turn_settings
from services.pipeline import build_turn_handling


def _cfg(**kw):
    return AppConfig(livekit_url="x", livekit_api_key="x", livekit_api_secret="x", deepgram_api_key="x",
                     google_api_key="x", cartesia_api_key="x", **kw)


def test_turn_settings_from_env(monkeypatch):
    monkeypatch.setenv("ENDPOINT_MIN_DELAY", "0.25")
    monkeypatch.setenv("PREEMPTIVE_GENERATION", "false")
    t = load_turn_settings()
    assert t.endpoint_min_delay == 0.25 and t.preemptive_generation is False


def test_turn_handling_shape_without_turn_detector():
    th = build_turn_handling(_cfg(use_turn_detector=False))
    assert th["turn_detection"] == "vad"
    assert set(th) == {"turn_detection", "endpointing", "interruption", "preemptive_generation"}
    assert th["endpointing"]["min_delay"] == 0.4


def test_thinking_config_per_gemini_generation():
    from services.gemini import thinking_config_for
    assert thinking_config_for("gemini-2.5-flash") == {"thinking_budget": 0}
    assert thinking_config_for("gemini-3.5-flash-lite") == {"thinking_level": "minimal"}
    assert thinking_config_for("models/gemini-3.8-flash", level="low") == {"thinking_level": "low"}


def test_room_options_noise_cancellation_modes():
    from services.pipeline import build_room_options
    assert build_room_options(_cfg(noise_cancellation="none")).get_audio_input_options().noise_cancellation is None
    nc = build_room_options(_cfg(noise_cancellation="bvc")).get_audio_input_options().noise_cancellation
    assert nc is not None


def test_groq_qwen_llm_gets_reasoning_none(monkeypatch):
    from services.pipeline import build_llm
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    llm = build_llm(_cfg(llm_provider="openai", llm_model="qwen/qwen3.8-27b", llm_api_key="k",
                         llm_base_url="https://api.groq.com/openai/v1", llm_reasoning_effort="none"))
    from livekit.agents.llm import FallbackAdapter
    assert isinstance(llm, FallbackAdapter)
    assert [x.model for x in llm._llm_instances] == ["qwen/qwen3.8-27b", "gemini-3.5-flash"]


def test_parse_llm_specs_handles_slashes_and_effort():
    from services.config import LLMSpec, parse_llm_specs
    assert parse_llm_specs("groq:qwen/qwen3.8-27b:none, google:gemini-3.5-flash,") == (
        LLMSpec("groq", "qwen/qwen3.8-27b", "none"), LLMSpec("google", "gemini-3.5-flash"))


def test_fallback_chain_skips_providers_without_keys(monkeypatch):
    from services.config import LLMSpec
    from services.pipeline import build_llm
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = _cfg(llm_provider="groq", llm_model="qwen/qwen3.8-27b", llm_reasoning_effort="none",
               llm_fallbacks=(LLMSpec("openai", "gpt-4.1-mini"), LLMSpec("google", "gemini-3.5-flash")))
    llm = build_llm(cfg)
    assert [x.model for x in llm._llm_instances] == ["qwen/qwen3.8-27b", "gemini-3.5-flash"]  # openai skipped: no key
