# Quality plan: voice, latency, noise, reliability

Every change here follows one loop: **change one thing → run the same test calls →
compare in Agent → Overview → "Versions compared"**. Publish each experiment as a
new agent version, so the dashboard is the experiment log.

Baseline (first platform call, Groq Qwen, `STT hi`, prompt v2):

| | p50 | p95 |
|---|---|---|
| Response (what the caller waits) | 1.50 s | 3.13 s |
| End of utterance | 1.01 s | 2.00 s |
| LLM first token | 276 ms | 1.22 s |
| TTS first audio | 101 ms | 112 ms |

Interrupted replies: 0 of 6 (old long prompt: 7 of 8). Cost: ₹2.77/min (no telephony yet).

## 1. Latency (always on)
The biggest share is now **end of utterance** (~1 s): the time between the caller
going quiet and us deciding they've finished. The LLM is no longer the bottleneck.

| # | Experiment | Expected | Risk |
|---|---|---|---|
| L1 | `endpoint_min_delay` 0.4 → 0.3 | −100 ms per turn | cuts off slow speakers |
| L2 | Endpointing mode `dynamic` (learns each caller's pause length) | lower p50 for fast talkers | new code path |
| L3 | Preemptive generation back **on** once Groq/OpenAI are on paid tiers | hides most of the LLM time | more tokens per turn |
| L4 | Fallback chain on paid keys: Groq → OpenAI `gpt-4.1-mini` → Gemini | p95 stops spiking on 429s | cost of the fallback model |
| L5 | Track **time to first audio after the caller stops** as the headline metric | one honest number | none |

Target: response p50 < 1.0 s, p95 < 2.0 s, with interrupted replies < 15%.

## 2. Voice quality
| # | Experiment | How to judge |
|---|---|---|
| V1 | Try 3–4 Cartesia Hindi voices (same script) | 5 people rate "sounds human / trustworthy" from 1 to 5 |
| V2 | Speed 1.0 / 1.1 / 1.2 | interrupted-reply rate + "too fast?" feedback |
| V3 | Numbers, dates and amounts always as words in the opening line and prompt | listen for wrong reads ("4200" vs "चार हज़ार दो सौ") |
| V4 | Pronunciation fixes for brand words (Voltly, EMI, CIBIL) | listen |
| V5 | Compare one more TTS (e.g. ElevenLabs Flash, Sarvam) on the same lines | TTFB + rating |

Must-have in the product: a voice picker with sample playback, and speed per agent (done).

## 3. Noise (not tested yet)
**Plan:** make noise repeatable instead of hoping to find it.
1. Record 5 short driver-style audio clips (Hinglish answers) in a quiet room.
2. Mix each with 3 backgrounds (traffic, crowd chatter, TV) at 2 loudness levels.
   That's 30 test inputs.
3. For each: STT word accuracy (vs the clean text), false interruptions,
   wrong-language transcripts.
4. Run with noise cancellation **off / BVC / BVCTelephony**, and STT `hi` vs `multi`.

Live check: 3 real calls from a road / market with earphones vs speakerphone.

Defences already in place:
- noise cancellation on the input (LiveKit BVC)
- `interrupt_min_duration` 0.5 s
- a prompt rule: garbled transcript → "please repeat", never hang up

Next lever if noise still interrupts the agent: `interrupt_min_words = 1`.

## 4. Reliability / fallbacks
- Paid Groq + OpenAI keys. Fallback chain per agent, configured in the UI (done).
- Dashboard shows **failover rate** per agent/version (done). Alert if > 5% (M2).
- Dispositions retry with backoff and switch models. The call record is saved first, so it is never lost.
