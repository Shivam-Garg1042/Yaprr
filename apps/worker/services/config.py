"""Environment configuration helpers.

Single source of truth for everything the worker reads from the environment:
the required provider credentials *and* the tunable voice-pipeline settings.
Non-engineers can change the voice, model, speed, latency knobs, safety limits
and pricing from `.env` without touching Python.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


REQUIRED_ENV_VARS = (
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "DEEPGRAM_API_KEY",
    "GOOGLE_API_KEY",
    "CARTESIA_API_KEY",
)

PLACEHOLDER_VALUES = {
    "",
    "your-project.livekit.cloud",
    "your_livekit_api_key",
    "your_livekit_api_secret",
    "your_deepgram_api_key",
    "your_google_api_key",
    "your_cartesia_api_key",
    "wss://your-project.livekit.cloud",
}

# Pipeline defaults. Override any of these in `.env` (see .env.example).
DEFAULT_STT_MODEL = "nova-3"
# gemini-2.5-flash returns 404 "no longer available to new users" (checked 2026-11-04).
DEFAULT_LLM_MODEL = "gemini-3.5-flash-lite"   # fastest Gemini that answered reliably in tests
DEFAULT_DISPOSITION_MODEL = "gemini-3.5-flash"  # post-call: accuracy > speed
DEFAULT_TTS_MODEL = "sonic-3"
DEFAULT_TTS_VOICE = "f786b574-daa5-4673-aa0c-cbe3e8534c02"
DEFAULT_TTS_LANGUAGE = "hi"
DEFAULT_TTS_SPEED = 1.1  # drivers said 1.0 felt slow ("fatafat batao")


@dataclass(frozen=True)
class LLMSpec:
    provider: str  # google | groq | openai | cerebras
    model: str
    reasoning_effort: str = ""


def parse_llm_specs(raw: str) -> tuple[LLMSpec, ...]:
    """"groq:qwen/qwen3.8-27b:none,google:gemini-3.5-flash" -> specs (model ids may contain '/')."""
    specs = []
    for item in filter(None, (x.strip() for x in raw.split(","))):
        provider, _, rest = item.partition(":")
        model, _, effort = rest.partition(":")
        if provider and model:
            specs.append(LLMSpec(provider.lower(), model, effort))
    return tuple(specs)


@dataclass(frozen=True)
class TurnSettings:
    """Latency / turn-taking knobs. See docs/BUILD_LOG.md (entry 2) for why each default."""

    # Silero VAD
    vad_min_speech: float = 0.05        # s of speech before VAD calls it "speech"
    vad_min_silence: float = 0.35       # s of silence before VAD calls speech "ended" (lib default 0.55)
    vad_activation: float = 0.5         # sensitivity; lower = picks up quieter speech
    # Endpointing (how long after speech ends before the agent replies)
    endpoint_min_delay: float = 0.4     # lib default 0.5
    endpoint_max_delay: float = 2.0     # cap when the turn detector thinks user isn't done (lib 3.0; first call hit it)
    # Interruptions (barge-in)
    allow_interruptions: bool = True
    interrupt_min_duration: float = 0.5  # s the user must speak to interrupt the agent
    interrupt_min_words: int = 0
    false_interruption_timeout: float = 2.0  # silence after a "cough" before agent resumes
    # Start generating the LLM reply before the turn is confirmed
    preemptive_generation: bool = True


@dataclass(frozen=True)
class SafetySettings:
    max_call_seconds: int = 360          # hard stop so a stuck call can't burn money
    user_away_timeout: float = 12.0      # s of mutual silence before user is "away"
    max_inactivity_prompts: int = 2      # "hello?" nudges before hanging up
    inactivity_message: str = "Hello Sir, क्या आप मेरी आवाज़ सुन पा रहे हैं?"
    closing_message: str = "समय देने के लिए धन्यवाद, आपका दिन शुभ हो।"


@dataclass(frozen=True)
class Pricing:
    """Unit prices used for the per-call cost estimate.

    Defaults are public list prices checked on 2026-11-04 and are estimates only;
    set the real numbers for your plan in `.env`.
    """

    stt_usd_per_min: float = 0.0077        # Deepgram Nova-3 streaming, pay-as-you-go
    llm_usd_per_m_input: float = 0.30      # Gemini 2.5 Flash, per 1M input tokens
    llm_usd_per_m_output: float = 2.50     # Gemini 2.5 Flash, per 1M output tokens
    tts_usd_per_m_chars: float = 45.0      # Cartesia: 1 credit/char; Startup overage $45/1M (Scale $38)
    platform_usd_per_min: float = 0.0      # LiveKit / telephony minutes, if you want them in
    usd_to_inr: float = 88.0


@dataclass(frozen=True)
class AppConfig:
    # Credentials
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    deepgram_api_key: str
    google_api_key: str
    cartesia_api_key: str

    # Local-dev / runtime
    events_log_path: str = "runtime/call_events.jsonl"
    call_records_dir: str = "runtime/calls"

    # Voice pipeline (tunable via env)
    stt_model: str = DEFAULT_STT_MODEL
    stt_language: str = "multi"           # try "hi" if Hinglish turns get mis-detected
    llm_provider: str = "google"          # google | openai (any OpenAI-compatible API via LLM_BASE_URL)
    llm_base_url: str = ""
    llm_reasoning_effort: str = ""          # openai-compatible: e.g. "none" for qwen on Groq, "low" for gpt-oss
    llm_api_key: str = ""                  # for openai-compatible providers (Groq/Cerebras); falls back to OPENAI_API_KEY
    # s before a *hanging* LLM request fails over. Errors (429/503) fail over instantly.
    # Must be >= 10: Gemini rejects request deadlines under 10 s (400 INVALID_ARGUMENT).
    llm_attempt_timeout: float = 10.0
    # Ordered fallback chain, tried when the primary errors or hangs. Env: LLM_FALLBACKS="openai:gpt-4.1-mini,google:gemini-3.5-flash"
    llm_fallbacks: tuple[LLMSpec, ...] = (LLMSpec("google", DEFAULT_DISPOSITION_MODEL),)
    noise_cancellation: str = "bvc"         # bvc (web/app audio) | bvc_telephony (phone calls) | none
    llm_vertex: bool = False                # Gemini via Vertex AI in a region you pick (needs gcloud ADC)
    llm_vertex_project: str = ""
    llm_vertex_location: str = "asia-south1"
    llm_model: str = DEFAULT_LLM_MODEL
    llm_temperature: float = 0.5
    llm_thinking_level: str = "minimal"    # Gemini 3.x: least thinking -> lowest TTFT
    llm_thinking_budget: int = 0           # Gemini 2.x only: 0 = no thinking tokens
    tts_model: str = DEFAULT_TTS_MODEL
    tts_voice: str = DEFAULT_TTS_VOICE
    tts_language: str = DEFAULT_TTS_LANGUAGE
    tts_speed: float = DEFAULT_TTS_SPEED
    use_turn_detector: bool = True

    turn: TurnSettings = field(default_factory=TurnSettings)
    safety: SafetySettings = field(default_factory=SafetySettings)
    pricing: Pricing = field(default_factory=Pricing)

    # Post-call analysis
    dispositions_enabled: bool = True
    disposition_model: str = DEFAULT_DISPOSITION_MODEL


def _is_placeholder(value: str | None) -> bool:
    if value is None:
        return True
    return value.strip() in PLACEHOLDER_VALUES


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return default if raw is None or raw.strip() == "" else float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return default if raw is None or raw.strip() == "" else int(raw)


def validate_required_env() -> None:
    missing = [name for name in REQUIRED_ENV_VARS if _is_placeholder(os.getenv(name))]
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(
            "Missing required environment variables: "
            f"{joined}. Copy .env.example to .env and set real values before starting the worker."
        )


def load_turn_settings() -> TurnSettings:
    d = TurnSettings()
    return TurnSettings(
        vad_min_speech=_env_float("VAD_MIN_SPEECH", d.vad_min_speech),
        vad_min_silence=_env_float("VAD_MIN_SILENCE", d.vad_min_silence),
        vad_activation=_env_float("VAD_ACTIVATION", d.vad_activation),
        endpoint_min_delay=_env_float("ENDPOINT_MIN_DELAY", d.endpoint_min_delay),
        endpoint_max_delay=_env_float("ENDPOINT_MAX_DELAY", d.endpoint_max_delay),
        allow_interruptions=_env_bool("ALLOW_INTERRUPTIONS", d.allow_interruptions),
        interrupt_min_duration=_env_float("INTERRUPT_MIN_DURATION", d.interrupt_min_duration),
        interrupt_min_words=_env_int("INTERRUPT_MIN_WORDS", d.interrupt_min_words),
        false_interruption_timeout=_env_float("FALSE_INTERRUPTION_TIMEOUT", d.false_interruption_timeout),
        preemptive_generation=_env_bool("PREEMPTIVE_GENERATION", d.preemptive_generation),
    )


def load_safety_settings() -> SafetySettings:
    d = SafetySettings()
    return SafetySettings(
        max_call_seconds=_env_int("MAX_CALL_SECONDS", d.max_call_seconds),
        user_away_timeout=_env_float("USER_AWAY_TIMEOUT", d.user_away_timeout),
        max_inactivity_prompts=_env_int("MAX_INACTIVITY_PROMPTS", d.max_inactivity_prompts),
        inactivity_message=os.getenv("INACTIVITY_MESSAGE", d.inactivity_message),
        closing_message=os.getenv("CLOSING_MESSAGE", d.closing_message),
    )


def load_pricing() -> Pricing:
    d = Pricing()
    return Pricing(
        stt_usd_per_min=_env_float("PRICE_STT_USD_PER_MIN", d.stt_usd_per_min),
        llm_usd_per_m_input=_env_float("PRICE_LLM_USD_PER_M_INPUT", d.llm_usd_per_m_input),
        llm_usd_per_m_output=_env_float("PRICE_LLM_USD_PER_M_OUTPUT", d.llm_usd_per_m_output),
        tts_usd_per_m_chars=_env_float("PRICE_TTS_USD_PER_M_CHARS", d.tts_usd_per_m_chars),
        platform_usd_per_min=_env_float("PRICE_PLATFORM_USD_PER_MIN", d.platform_usd_per_min),
        usd_to_inr=_env_float("USD_TO_INR", d.usd_to_inr),
    )


def load_app_config() -> AppConfig:
    validate_required_env()
    return AppConfig(
        livekit_url=os.environ["LIVEKIT_URL"],
        livekit_api_key=os.environ["LIVEKIT_API_KEY"],
        livekit_api_secret=os.environ["LIVEKIT_API_SECRET"],
        deepgram_api_key=os.environ["DEEPGRAM_API_KEY"],
        google_api_key=os.environ["GOOGLE_API_KEY"],
        cartesia_api_key=os.environ["CARTESIA_API_KEY"],
        events_log_path=os.getenv("EVENTS_LOG_PATH", "runtime/call_events.jsonl"),
        call_records_dir=os.getenv("CALL_RECORDS_DIR", "runtime/calls"),
        stt_model=os.getenv("STT_MODEL", DEFAULT_STT_MODEL),
        stt_language=os.getenv("STT_LANGUAGE", "multi"),
        llm_provider=os.getenv("LLM_PROVIDER", "google").lower(),
        llm_base_url=os.getenv("LLM_BASE_URL", ""),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        llm_reasoning_effort=os.getenv("LLM_REASONING_EFFORT", ""),
        noise_cancellation=os.getenv("NOISE_CANCELLATION", "bvc").lower(),
        llm_attempt_timeout=max(10.0, _env_float("LLM_ATTEMPT_TIMEOUT", 10.0)),
        llm_fallbacks=parse_llm_specs(os.getenv("LLM_FALLBACKS", f"google:{DEFAULT_DISPOSITION_MODEL}")),
        llm_vertex=_env_bool("LLM_VERTEX", False),
        llm_vertex_project=os.getenv("GOOGLE_CLOUD_PROJECT", ""),
        llm_vertex_location=os.getenv("GOOGLE_CLOUD_LOCATION", "asia-south1"),
        llm_model=os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL),
        llm_temperature=_env_float("LLM_TEMPERATURE", 0.5),
        llm_thinking_level=os.getenv("LLM_THINKING_LEVEL", "minimal"),
        llm_thinking_budget=_env_int("LLM_THINKING_BUDGET", 0),
        tts_model=os.getenv("TTS_MODEL", DEFAULT_TTS_MODEL),
        tts_voice=os.getenv("TTS_VOICE", DEFAULT_TTS_VOICE),
        tts_language=os.getenv("TTS_LANGUAGE", DEFAULT_TTS_LANGUAGE),
        tts_speed=float(os.getenv("TTS_SPEED", str(DEFAULT_TTS_SPEED))),
        use_turn_detector=_env_bool("USE_TURN_DETECTOR", True),
        turn=load_turn_settings(),
        safety=load_safety_settings(),
        pricing=load_pricing(),
        dispositions_enabled=_env_bool("DISPOSITIONS_ENABLED", True),
        disposition_model=os.getenv("DISPOSITION_MODEL", DEFAULT_DISPOSITION_MODEL),
    )
