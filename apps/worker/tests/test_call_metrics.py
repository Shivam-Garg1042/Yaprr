from livekit.agents.metrics import EOUMetrics, LLMMetrics, STTMetrics, TTSMetrics

from services.call_metrics import CallMetrics, percentile
from services.config import Pricing


def _llm(sid, ttft, pin=1000, pout=50, cancelled=False):
    return LLMMetrics(label="llm", request_id="r", timestamp=0, duration=1, ttft=ttft, cancelled=cancelled,
                      completion_tokens=pout, prompt_tokens=pin, prompt_cached_tokens=0, total_tokens=pin + pout,
                      tokens_per_second=50, speech_id=sid)


def _tts(sid, ttfb, chars=60):
    return TTSMetrics(label="tts", request_id="r", timestamp=0, ttfb=ttfb, duration=1, audio_duration=3,
                      cancelled=False, characters_count=chars, streamed=True, speech_id=sid)


def _eou(sid, delay):
    return EOUMetrics(timestamp=0, end_of_utterance_delay=delay, transcription_delay=0.1,
                      on_user_turn_completed_delay=0, speech_id=sid)


def test_percentile_nearest_rank():
    assert percentile([], 50) is None
    assert percentile([1, 2, 3, 4], 50) == 2
    assert percentile([1, 2, 3, 4], 95) == 4


def test_turn_latency_is_eou_plus_ttft_plus_ttfb():
    m = CallMetrics()
    for sid, (e, l, t) in {"s1": (0.4, 0.3, 0.2), "s2": (0.6, 0.5, 0.3)}.items():
        m.on_metrics(_eou(sid, e)); m.on_metrics(_llm(sid, l)); m.on_metrics(_tts(sid, t))
    lat = m.latency_summary()["response"]
    assert lat["n"] == 2
    assert lat["p50_ms"] == 900.0 and lat["p95_ms"] == 1400.0


def test_incomplete_and_cancelled_turns_are_ignored_for_latency():
    m = CallMetrics()
    m.on_metrics(_llm("s1", 0.3, cancelled=True))   # cancelled preemptive attempt
    m.on_metrics(_llm("s1", 0.25))
    m.on_metrics(_tts("s1", 0.2)); m.on_metrics(_eou("s1", 0.4))
    m.on_metrics(_llm("greeting", 0.3)); m.on_metrics(_tts("greeting", 0.2))  # agent speaks first: no EOU
    lat = m.latency_summary()
    assert lat["response"]["n"] == 1 and lat["response"]["p50_ms"] == 850.0
    assert lat["llm_ttft"]["n"] == 2


def test_cost_estimate():
    p = Pricing(stt_usd_per_min=0.01, llm_usd_per_m_input=1.0, llm_usd_per_m_output=10.0,
                tts_usd_per_m_chars=50.0, platform_usd_per_min=0.0, usd_to_inr=100.0)
    m = CallMetrics(pricing=p)
    m.on_metrics(STTMetrics(label="stt", request_id="r", timestamp=0, duration=0, audio_duration=120, streamed=True))
    m.on_metrics(_llm("s", 0.3, pin=10_000, pout=1_000))
    m.on_metrics(_tts("s", 0.2, chars=2_000))
    c = m.cost_summary(call_seconds=120)
    # stt 0.02 + llm 0.01+0.01 + tts 0.1 = 0.14 USD -> 14 INR over 2 min
    assert c["usd"]["total"] == 0.14
    assert c["inr_total"] == 14.0 and c["inr_per_minute"] == 7.0
    assert c["inr"]["tts"] == 10.0 and c["inr"]["total"] == 14.0
