"""Benchmark conversation LLMs for the voice agent: streaming TTFT + reply sample.

Uses the REAL Neha system prompt and a real Hindi driver line, so the numbers
match what a call would see. Run from the repo root with your venv active:

    python scripts/llm_bench.py                       # every provider you have a key for
    python scripts/llm_bench.py --runs 8
    python scripts/llm_bench.py --only groq

Keys read from .env: GOOGLE_API_KEY, OPENAI_API_KEY, GROQ_API_KEY, CEREBRAS_API_KEY.
Override model lists with --google/--openai/--groq/--cerebras "model1,model2".
Model names change often: if one 404s, check the provider's model list.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402

from services.call_metrics import percentile  # noqa: E402
from services.gemini import thinking_config_for  # noqa: E402

load_dotenv()

DRIVER_LINE = "पच्चीस October को तो मैंने पैसे दे दिए थे, अब फिर से क्यों call कर रहे हो?"

DEFAULTS = {
    "google": "gemini-3.5-flash-lite,gemini-3.5-flash",
    "openai": "gpt-4.1-mini,gpt-4.1-nano,gpt-4o-mini",
    "groq": "qwen/qwen3.8-27b,openai/gpt-oss-20b",
    "cerebras": "llama-3.3-70b,gpt-oss-120b",
}
OPENAI_COMPAT = {
    "openai": ("OPENAI_API_KEY", None),
    "groq": ("GROQ_API_KEY", "https://api.groq.com/openai/v1"),
    "cerebras": ("CEREBRAS_API_KEY", "https://api.cerebras.ai/v1"),
}


def system_prompt() -> str:
    """The real instructions of the bundled demo collections agent (voice rules + prompt)."""
    import json

    from agents.configured_agent import ConfiguredAgent
    from services.runtime import LOCAL_DEMO

    demo = json.loads(LOCAL_DEMO.read_text(encoding="utf-8"))
    return ConfiguredAgent(demo["config"], demo["context"], emit=lambda *_: None).instructions


async def ttft_google(model: str, sys_prompt: str) -> tuple[float, str]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    cfg = types.GenerateContentConfig(system_instruction=sys_prompt, temperature=0.5,
                                      thinking_config=types.ThinkingConfig(**thinking_config_for(model)))
    t0, first, text = time.perf_counter(), None, ""
    async for chunk in await client.aio.models.generate_content_stream(model=model, contents=DRIVER_LINE, config=cfg):
        if chunk.text:
            first = first or time.perf_counter() - t0
            text += chunk.text
    if first is None:
        raise RuntimeError("no text returned (reasoning used all tokens?)")
    return first, text


async def ttft_openai_compat(provider: str, model: str, sys_prompt: str) -> tuple[float, str]:
    from openai import AsyncOpenAI

    key_env, base = OPENAI_COMPAT[provider]
    client = AsyncOpenAI(api_key=os.environ[key_env], base_url=base)
    t0, first, text = time.perf_counter(), None, ""
    extra = {}
    if provider != "openai":  # fastest reasoning setting for Groq/Cerebras open models
        extra = {"reasoning_effort": "low", "reasoning_format": "hidden"} if "gpt-oss" in model \
            else {"reasoning_effort": "none"} if "qwen" in model else {}
    stream = await client.chat.completions.create(
        model=model, stream=True, temperature=0.5, max_tokens=300, extra_body=extra or None,
        messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": DRIVER_LINE}],
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            first = first or time.perf_counter() - t0
            text += delta
    if first is None:
        raise RuntimeError("no text returned (reasoning used all tokens?)")
    return first, text


async def bench(provider: str, model: str, runs: int, sys_prompt: str) -> None:
    times, sample, errors = [], "", 0
    for _ in range(runs):
        try:
            if provider == "google":
                t, txt = await ttft_google(model, sys_prompt)
            else:
                t, txt = await ttft_openai_compat(provider, model, sys_prompt)
            times.append(t)
            sample = sample or txt
        except Exception as exc:  # noqa: BLE001
            errors += 1
            sample = sample or f"ERROR: {str(exc)[:120]}"
    p50, p95 = percentile(times, 50), percentile(times, 95)
    fmt = lambda x: "-" if x is None else f"{x * 1000:.0f}ms"  # noqa: E731
    print(f"{provider:9} {model:28} TTFT p50 {fmt(p50):>7}  p95 {fmt(p95):>7}  errors {errors}/{runs}")
    print(f"          reply: {sample.strip()[:160]}\n")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--only", default="")
    for p in DEFAULTS:
        ap.add_argument(f"--{p}", default=DEFAULTS[p])
    args = ap.parse_args()

    key_for = {"google": "GOOGLE_API_KEY", **{p: v[0] for p, v in OPENAI_COMPAT.items()}}
    sys_prompt = system_prompt()
    print(f"System prompt ≈ {len(sys_prompt)} chars. Driver: {DRIVER_LINE}\n")
    for provider in DEFAULTS:
        if args.only and provider != args.only:
            continue
        if not os.getenv(key_for[provider]):
            print(f"{provider:9} skipped (no {key_for[provider]} in .env)\n")
            continue
        for model in getattr(args, provider).split(","):
            await bench(provider, model.strip(), args.runs, sys_prompt)


if __name__ == "__main__":
    asyncio.run(main())
