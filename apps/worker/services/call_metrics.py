"""Per-call latency + usage + cost tracking.

LiveKit emits a metrics event for every STT / LLM / TTS / end-of-utterance step.
We group them by `speech_id` (one agent reply = one speech) so we can say, for
each turn, how long the caller waited:

    response latency ~= end_of_utterance_delay + llm.ttft + tts.ttfb

  - end_of_utterance_delay: user stopped talking -> we decided their turn ended
  - llm ttft: request sent -> first token back
  - tts ttfb: first text in -> first audio byte out

With preemptive generation the LLM can start before the turn is confirmed, so
this sum is a slight over-estimate (a safe upper bound).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from livekit.agents.metrics import EOUMetrics, LLMMetrics, STTMetrics, TTSMetrics

from services.config import Pricing


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile. Returns None for an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def _stats(values: list[float]) -> dict[str, float | None]:
    return {
        "p50_ms": _ms(percentile(values, 50)),
        "p95_ms": _ms(percentile(values, 95)),
        "max_ms": _ms(max(values) if values else None),
        "n": len(values),
    }


def _ms(seconds: float | None) -> float | None:
    return None if seconds is None else round(seconds * 1000, 1)


@dataclass
class _Turn:
    eou_delay: float | None = None
    transcription_delay: float | None = None
    llm_ttft: float | None = None
    tts_ttfb: float | None = None

    @property
    def total(self) -> float | None:
        if None in (self.eou_delay, self.llm_ttft, self.tts_ttfb):
            return None
        return self.eou_delay + self.llm_ttft + self.tts_ttfb  # type: ignore[operator]


@dataclass
class Usage:
    stt_audio_seconds: float = 0.0
    llm_input_tokens: int = 0
    llm_cached_tokens: int = 0
    llm_output_tokens: int = 0
    llm_requests: int = 0
    tts_characters: int = 0
    tts_audio_seconds: float = 0.0
    llm_requests_by_model: dict[str, int] = field(default_factory=dict)  # shows how often fallbacks served
    llm_failovers: int = 0  # primary marked unavailable during the call


@dataclass
class CallMetrics:
    pricing: Pricing = field(default_factory=Pricing)
    usage: Usage = field(default_factory=Usage)
    _turns: dict[str, _Turn] = field(default_factory=dict)

    def _turn(self, speech_id: str | None) -> _Turn | None:
        if not speech_id:
            return None
        return self._turns.setdefault(speech_id, _Turn())

    def on_metrics(self, m: Any) -> None:
        """Feed every `metrics_collected` event's `.metrics` in here."""
        if isinstance(m, STTMetrics):
            self.usage.stt_audio_seconds += m.audio_duration
        elif isinstance(m, LLMMetrics):
            self.usage.llm_input_tokens += m.prompt_tokens
            self.usage.llm_cached_tokens += m.prompt_cached_tokens
            self.usage.llm_output_tokens += m.completion_tokens
            self.usage.llm_requests += 1
            model = (m.metadata.model_name if m.metadata else None) or m.label
            self.usage.llm_requests_by_model[model] = self.usage.llm_requests_by_model.get(model, 0) + 1
            turn = self._turn(m.speech_id)
            if turn is not None and not m.cancelled and turn.llm_ttft is None:
                turn.llm_ttft = m.ttft
        elif isinstance(m, TTSMetrics):
            self.usage.tts_characters += m.characters_count
            self.usage.tts_audio_seconds += m.audio_duration
            turn = self._turn(m.speech_id)
            if turn is not None and not m.cancelled and turn.tts_ttfb is None:
                turn.tts_ttfb = m.ttfb  # first audio chunk of the reply is what the caller hears
        elif isinstance(m, EOUMetrics):
            turn = self._turn(m.speech_id)
            if turn is not None:
                turn.eou_delay = m.end_of_utterance_delay
                turn.transcription_delay = m.transcription_delay

    # ── reporting ────────────────────────────────────────────────────────────
    def latency_summary(self) -> dict[str, Any]:
        turns = list(self._turns.values())
        pick = lambda attr: [getattr(t, attr) for t in turns if getattr(t, attr) is not None]  # noqa: E731
        totals = [t.total for t in turns if t.total is not None]
        return {
            "response": _stats(totals),
            "end_of_utterance": _stats(pick("eou_delay")),
            "transcription": _stats(pick("transcription_delay")),
            "llm_ttft": _stats(pick("llm_ttft")),
            "tts_ttfb": _stats(pick("tts_ttfb")),
        }

    def cost_summary(self, call_seconds: float) -> dict[str, Any]:
        p, u = self.pricing, self.usage
        stt = u.stt_audio_seconds / 60 * p.stt_usd_per_min
        llm = (u.llm_input_tokens * p.llm_usd_per_m_input + u.llm_output_tokens * p.llm_usd_per_m_output) / 1e6
        tts = u.tts_characters * p.tts_usd_per_m_chars / 1e6
        platform = call_seconds / 60 * p.platform_usd_per_min
        total = stt + llm + tts + platform
        minutes = call_seconds / 60 if call_seconds > 0 else 0
        return {
            "usd": {k: round(v, 5) for k, v in
                    {"stt": stt, "llm": llm, "tts": tts, "platform": platform, "total": total}.items()},
            "inr_total": round(total * p.usd_to_inr, 3),
            "inr_per_minute": round(total * p.usd_to_inr / minutes, 3) if minutes else None,
            "note": "estimate from unit prices in config.Pricing",
        }

    def summary(self, call_seconds: float) -> dict[str, Any]:
        return {
            "latency": self.latency_summary(),
            "usage": {**self.usage.__dict__, "llm_requests_by_model": dict(self.usage.llm_requests_by_model)},
            "cost": self.cost_summary(call_seconds),
        }
