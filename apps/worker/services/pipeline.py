"""Voice pipeline construction.

Centralizes how the STT -> LLM -> TTS -> VAD -> turn-detection stack is wired
so the rest of the app never hard-codes model names or voice ids. `main.py`
just asks for a session; swapping a provider happens here (and via `.env`).
"""

from __future__ import annotations

import logging
import os

from livekit.agents import AgentSession
from livekit.agents.vad import VAD
# All LiveKit plugins MUST be imported at module level: plugins register
# themselves on import, and registration only works on the main thread.
# Importing one lazily inside the job (a worker thread) crashes the call with
# "Plugins must be registered on the main thread".
from livekit.agents import llm as lk_llm
from livekit.agents import room_io
from livekit.plugins import cartesia, deepgram, google, noise_cancellation, openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from services.config import AppConfig, TurnSettings
from services.gemini import thinking_config_for

logger = logging.getLogger(__name__)


def load_vad(turn: TurnSettings | None = None) -> VAD:
    """Load the Silero VAD. Call this once at prewarm, not per call."""
    turn = turn or TurnSettings()
    return silero.VAD.load(
        min_speech_duration=turn.vad_min_speech,
        min_silence_duration=turn.vad_min_silence,
        activation_threshold=turn.vad_activation,
    )


def build_turn_handling(config: AppConfig) -> dict:
    """LiveKit 1.5 `turn_handling` options built from our env-driven settings."""
    t = config.turn
    return {
        "turn_detection": MultilingualModel() if config.use_turn_detector else "vad",
        "endpointing": {"min_delay": t.endpoint_min_delay, "max_delay": t.endpoint_max_delay},
        "interruption": {
            "enabled": t.allow_interruptions,
            "min_duration": t.interrupt_min_duration,
            "min_words": t.interrupt_min_words,
            "false_interruption_timeout": t.false_interruption_timeout,
            "resume_false_interruption": True,
        },
        "preemptive_generation": {"enabled": t.preemptive_generation},
    }


def build_llm(config: AppConfig):
    """Primary LLM + ordered fallbacks, wrapped in LiveKit's FallbackAdapter.

    Seen in testing: Gemini 503 "high demand" and Groq free-tier 429s. Without
    fallbacks the agent goes silent mid-call. With them, a request that errors
    (instantly) or hangs (> attempt_timeout) is retried on the next model, and
    the failed one is health-checked in the background.
    Cross-provider on purpose: two models on the same provider share an outage.
    """
    primary = _llm_for(config, config.llm_provider, config.llm_model, config.llm_reasoning_effort, primary=True)
    chain = [primary]
    for spec in config.llm_fallbacks:
        if (spec.provider, spec.model) == (config.llm_provider, config.llm_model):
            continue
        try:
            chain.append(_llm_for(config, spec.provider, spec.model, spec.reasoning_effort))
        except Exception as exc:  # noqa: BLE001 - e.g. missing key for that provider
            logger.warning("[yaprr] skipping fallback %s:%s (%s)", spec.provider, spec.model, exc)
    if len(chain) == 1:
        return primary
    return lk_llm.FallbackAdapter(chain, attempt_timeout=config.llm_attempt_timeout)


def _google_llm(config: AppConfig, model: str):
    vertex = {}
    if config.llm_vertex:
        # Region-pinned Gemini: auth via `gcloud auth application-default login`
        vertex = {"vertexai": True, "project": config.llm_vertex_project or None,
                  "location": config.llm_vertex_location}
        vertex = {k: v for k, v in vertex.items() if v is not None}
    else:
        vertex = {"api_key": config.google_api_key}
    return google.LLM(
        model=model,
        temperature=config.llm_temperature,
        **vertex,
        thinking_config=thinking_config_for(
            model, level=config.llm_thinking_level, budget=config.llm_thinking_budget
        ),
    )


# OpenAI-compatible providers: default base URL + the env var holding the key.
OPENAI_COMPATIBLE = {
    "openai": (None, "OPENAI_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "cerebras": ("https://api.cerebras.ai/v1", "CEREBRAS_API_KEY"),
}


def _llm_for(config: AppConfig, provider: str, model: str, effort: str = "", primary: bool = False):
    """Build one LLM. LLM_BASE_URL / LLM_API_KEY overrides apply to the primary only."""
    if provider == "google":
        return _google_llm(config, model)
    if provider not in OPENAI_COMPATIBLE:
        raise ValueError(f"unknown LLM provider {provider!r}")
    default_url, key_env = OPENAI_COMPATIBLE[provider]
    base_url = (config.llm_base_url if primary else "") or default_url
    api_key = (config.llm_api_key if primary else "") or os.getenv(key_env, "")
    if not api_key:
        raise ValueError(f"{key_env} is not set")
    kwargs = {"model": model, "temperature": config.llm_temperature, "api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    if effort and not (provider == "openai" and effort == "none"):
        # Sent raw so provider-specific values like Groq's "none" pass through.
        extra = {"reasoning_effort": effort}
        if "gpt-oss" in model and provider != "openai":
            extra["reasoning_format"] = "hidden"  # Groq/Cerebras: don't stream reasoning text
        kwargs["extra_body"] = extra
    return openai.LLM(**kwargs)


def build_session(config: AppConfig, vad: VAD) -> AgentSession:
    """Build a fully-configured AgentSession from app config + a prewarmed VAD."""
    logger.info(
        "[yaprr] Pipeline: stt=%s llm=%s:%s(temp=%s, thinking=%s) tts=%s/%s turn_detector=%s "
        "endpoint=%.2f-%.2fs preemptive=%s",
        config.stt_model,
        config.llm_provider,
        config.llm_model,
        config.llm_temperature,
        thinking_config_for(config.llm_model, level=config.llm_thinking_level, budget=config.llm_thinking_budget),
        config.tts_model,
        config.tts_language,
        config.use_turn_detector,
        config.turn.endpoint_min_delay,
        config.turn.endpoint_max_delay,
        config.turn.preemptive_generation,
    )

    return AgentSession(
        stt=deepgram.STT(model=config.stt_model, language=config.stt_language),
        llm=build_llm(config),
        tts=cartesia.TTS(
            model=config.tts_model,
            voice=config.tts_voice,
            language=config.tts_language,
            speed=config.tts_speed,
        ),
        vad=vad,
        turn_handling=build_turn_handling(config),
        user_away_timeout=config.safety.user_away_timeout,
    )


def build_room_options(config: AppConfig):
    """Noise cancellation on the caller's incoming audio, before VAD/STT see it.

    Cleaner input means fewer false "speech" detections from traffic/horns, fewer
    garbage transcripts, and fewer accidental interruptions. LiveKit's BVC also
    removes background *voices* (other people near the driver). Needs LiveKit
    Cloud. Not applied in `console` mode (local mic). Test with `dev` + playground.
    """
    mode = config.noise_cancellation
    if mode in ("", "none", "off", "false"):
        return room_io.RoomOptions()
    nc = noise_cancellation.BVCTelephony() if mode == "bvc_telephony" else noise_cancellation.BVC()
    return room_io.RoomOptions(audio_input=room_io.AudioInputOptions(noise_cancellation=nc))
