"""Run the golden set against an agent: simulated callers, scored by code and an LLM judge.

    python -m evals.run                                  # local demo agent, every persona once
    python -m evals.run --agent-id <id> --version 2      # a published version from the API
    python -m evals.run --runs 3 --only promise_date,brother_answers

How it works (text-only, no audio, so it's fast and cheap):
- The REAL agent: the same ConfiguredAgent, prompt, tools and read-back gate as a live
  call, on the agent's own LLM + fallbacks. Only STT/TTS are skipped.
- A caller LLM plays one persona from golden_set.json and only knows its own facts.
- Scoring: code checks (scoring.py) + an LLM judge for the per-persona criteria.
- LLMs are random, so --runs N repeats each persona and reports pass *rates*.

Output: evals/results/<time>_<agent>_v<version>.json and .md (the table for the README).
Caller and judge use EVAL_LLM (default openai:gpt-4.1-mini). Their cost isn't counted;
the reported cost is the agent's own LLM usage per simulated call.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()
for _k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "DEEPGRAM_API_KEY", "CARTESIA_API_KEY",
           "GOOGLE_API_KEY"):  # no room, STT or TTS in text evals; a missing Google key only disables that fallback
    os.environ.setdefault(_k, "unused-in-evals")

from livekit.agents import AgentSession  # noqa: E402
from livekit.agents.llm import ChatContext  # noqa: E402

from agents.configured_agent import ConfiguredAgent  # noqa: E402
from evals import scoring  # noqa: E402
from services.call_metrics import CallMetrics  # noqa: E402
from services.config import load_app_config  # noqa: E402
from services.pipeline import _llm_for, build_llm  # noqa: E402
from services.pricing import pricing_for  # noqa: E402
from services.runtime import apply_agent_overrides, resolve_agent  # noqa: E402

HERE = Path(__file__).resolve().parent
MAX_TURNS = 12
END = "<END>"

CALLER_SYSTEM = """You are role-playing a person receiving a phone call, to test a voice agent.
Persona (secret, only you know this): {persona}

Rules:
- Reply like a real Indian e-rickshaw driver on the phone: short (1-2 sentences), Hinglish unless the persona says otherwise.
- Stay in character. Reveal facts only when they come up naturally.
- Don't help the agent. Don't invent facts beyond the persona.
- If the agent says goodbye / ends the call, or you would hang up now, reply with exactly {end}."""

JUDGE_SYSTEM = """You grade a phone call between a collections voice agent ("agent") and a caller.
Tool calls the agent made are shown as [tool ...] lines; "NOT done yet" outputs are read-back prompts, not actions.
The caller's hidden persona: {persona}

Grade each criterion strictly from the transcript. Reply with JSON only:
{{"criteria": [{{"criterion": "...", "pass": true|false, "why": "short reason"}}]}}

Criteria:
{criteria}"""

GENERAL_CRITERIA = [
    "The agent did not invent amounts, dates, fees or policies that aren't supported by the conversation.",
    "The agent stayed polite and did not threaten or shame the caller.",
]


async def complete(llm: Any, system: str, messages: list[tuple[str, str]]) -> str:
    ctx = ChatContext()
    ctx.add_message(role="system", content=system)
    for role, text in messages:
        ctx.add_message(role=role, content=text)
    out = []
    async with llm.chat(chat_ctx=ctx) as stream:
        async for chunk in stream:
            if chunk.delta and chunk.delta.content:
                out.append(chunk.delta.content)
    return "".join(out).strip()


def render(turns: list[dict]) -> str:
    lines = []
    for t in turns:
        if t["role"] == "tool":
            lines.append(f"[tool {t['name']}({json.dumps(t['args'], ensure_ascii=False)}) -> {t['output'][:160]}]")
        else:
            lines.append(f"{t['role']}: {t['text']}")
    return "\n".join(lines)


async def caller_reply(llm: Any, persona: dict, turns: list[dict]) -> str | None:
    # From the caller's side the agent is the "user" and the caller is the "assistant".
    msgs = [("user" if t["role"] == "agent" else "assistant", t["text"]) for t in turns if t["role"] != "tool"]
    text = await complete(llm, CALLER_SYSTEM.format(persona=persona["caller"], end=END), msgs)
    return None if not text or END in text else text


async def judge(llm: Any, persona: dict, turns: list[dict]) -> list[dict]:
    criteria = persona.get("judge", []) + GENERAL_CRITERIA
    system = JUDGE_SYSTEM.format(persona=persona["caller"], criteria="\n".join(f"- {c}" for c in criteria))
    raw = await complete(llm, system, [("user", render(turns))])
    try:
        data = json.loads(re.search(r"\{.*\}", raw, re.S).group())
        return [{"criterion": c.get("criterion", ""), "pass": bool(c.get("pass")), "why": c.get("why", "")}
                for c in data.get("criteria", [])]
    except Exception:  # noqa: BLE001
        return [{"criterion": "judge output parse", "pass": False, "why": raw[:200]}]


async def simulate(persona: dict, agent_cfg: dict, context: dict, config: Any, caller_llm: Any,
                   turn_delay: float = 0) -> dict:
    call_metrics = CallMetrics(pricing=config.pricing)
    session = AgentSession(llm=build_llm(config))
    session.on("metrics_collected", lambda ev: call_metrics.on_metrics(ev.metrics))
    agent = ConfiguredAgent(agent_cfg, context, emit=lambda *_: None, call_key=f"eval-{persona['id']}")

    async def _no_greeting() -> None:  # text mode: the opening line goes into history instead of TTS
        return None
    agent.on_enter = _no_greeting
    opening = agent.opening_line
    chat_ctx = agent.chat_ctx.copy()
    chat_ctx.add_message(role="assistant", content=opening)
    await agent.update_chat_ctx(chat_ctx)

    turns: list[dict] = [{"role": "agent", "text": opening}]
    turn_ms: list[float] = []
    error = None
    await session.start(agent)
    try:
        for _ in range(MAX_TURNS):
            if turn_delay and len(turns) > 1:
                await asyncio.sleep(turn_delay)  # stay under free-tier tokens-per-minute limits
            said = await caller_reply(caller_llm, persona, turns)
            if said is None:
                break
            turns.append({"role": "caller", "text": said})
            t0 = time.perf_counter()
            result = await asyncio.wait_for(session.run(user_input=said), timeout=60)
            turn_ms.append((time.perf_counter() - t0) * 1000)
            hung_up = False
            for ev in result.events:
                item = ev.item
                if ev.type == "message" and item.role == "assistant" and item.text_content:
                    turns.append({"role": "agent", "text": item.text_content})
                elif ev.type == "function_call":
                    try:
                        args = json.loads(item.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {"raw": item.arguments}
                    turns.append({"role": "tool", "name": item.name, "args": args, "output": "", "_id": item.call_id})
                    hung_up |= item.name == "hangup"
                elif ev.type == "function_call_output":
                    for t in reversed(turns):
                        if t.get("_id") == item.call_id:
                            t["output"] = str(item.output)
                            break
            if hung_up:
                break
    except Exception as exc:  # noqa: BLE001 - one broken conversation shouldn't stop the run
        error = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            await session.aclose()
        except Exception:  # noqa: BLE001
            pass
    for t in turns:
        t.pop("_id", None)
    return {"turns": turns, "turn_ms": turn_ms, "error": error,
            "cost_inr": call_metrics.cost_summary(call_seconds=0)["inr_total"]}


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agent-id", default=None, help="agent from the API (needs YAPRR_API_URL); default: local demo agent")
    ap.add_argument("--version", type=int, default=None, help="published version (default: latest)")
    ap.add_argument("--runs", type=int, default=1, help="repeat each persona N times")
    ap.add_argument("--only", default="", help="comma-separated persona ids")
    ap.add_argument("--concurrency", type=int, default=2, help="conversations in parallel (mind free-tier rate limits)")
    ap.add_argument("--turn-delay", type=float, default=0, help="seconds to wait between turns (free tiers: try 20)")
    args = ap.parse_args()

    golden = json.loads((HERE / "golden_set.json").read_text(encoding="utf-8"))
    personas = [p for p in golden["personas"] if not args.only or p["id"] in args.only.split(",")]
    meta = json.dumps({"agent_id": args.agent_id, "version": args.version}) if args.agent_id else None
    resolved = await resolve_agent(meta)
    config = apply_agent_overrides(load_app_config(), resolved.config)
    config = dataclasses.replace(config, pricing=pricing_for(config))
    context = {**resolved.context, **golden.get("agent_context", {})}

    provider, model = os.getenv("EVAL_LLM", "openai:gpt-4.1-mini").split(":", 1)
    caller_llm = _llm_for(dataclasses.replace(config, llm_temperature=0.7), provider, model)
    judge_llm = _llm_for(dataclasses.replace(config, llm_temperature=0.0), provider, model)

    print(f"Agent: {resolved.name} v{resolved.version or 'local'} | LLM {config.llm_provider}:{config.llm_model} | "
          f"{len(personas)} personas x {args.runs} | caller/judge {provider}:{model}")
    sem = asyncio.Semaphore(args.concurrency)

    async def one(p: dict, run: int) -> dict:
        async with sem:
            sim = await simulate(p, resolved.config, context, config, caller_llm, args.turn_delay)
            checks = scoring.check(p, sim["turns"])
            verdicts = await judge(judge_llm, p, sim["turns"]) if not sim["error"] else []
            passed = not sim["error"] and all(checks.values()) and bool(verdicts) and all(v["pass"] for v in verdicts)
            r = {"persona": p["id"], "run": run, "passed": passed, "checks": checks, "judge": verdicts,
                 "key_facts_correct": scoring.key_facts_correct(p, sim["turns"]),
                 "reply_words": scoring.reply_words(sim["turns"]), **sim}
            failed = [k for k, v in checks.items() if not v] + [v["criterion"] for v in verdicts if not v["pass"]]
            print(f"  {'PASS' if passed else 'FAIL'}  {p['id']:<20} run {run}"
                  + (f"  error: {sim['error']}" if sim["error"] else "")
                  + (f"  failed: {'; '.join(failed)[:160]}" if failed else ""))
            return r

    results = await asyncio.gather(*(one(p, r) for p in personas for r in range(1, args.runs + 1)))
    summary = scoring.summarize(results)

    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    name = f"{stamp}_{(resolved.agent_id or 'local')}_v{resolved.version or 0}"
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    (out / f"{name}.json").write_text(json.dumps({"agent": resolved.name, "version": resolved.version,
                                                  "llm": f"{config.llm_provider}:{config.llm_model}",
                                                  "summary": summary, "results": results},
                                                 ensure_ascii=False, indent=2), encoding="utf-8")
    md = to_markdown(resolved.name, resolved.version, f"{config.llm_provider}:{config.llm_model}", summary, results)
    (out / f"{name}.md").write_text(md, encoding="utf-8")
    print("\n" + md + f"\nSaved evals/results/{name}.json and .md")


def to_markdown(agent: str, version: int | None, llm: str, s: dict, results: list[dict]) -> str:
    f = lambda v, pct=False: "—" if v is None else (f"{v * 100:.0f}%" if pct else f"{v:.0f}")  # noqa: E731
    rows = [
        f"**{agent} v{version or 'local'}** · LLM `{llm}` · {s['conversations']} simulated calls · {s['errors']} errors",
        "",
        "| Metric | Result |",
        "|---|---|",
        f"| Task success (all checks + judge) | {f(s['task_success'], True)} |",
        f"| Key-fact accuracy (promise date + amount) | {f(s['key_fact_accuracy'], True)} |",
        f"| Read back before acting | {f(s['readback_rate'], True)} |",
        f"| Replies ≤ 20 words | {f(s['short_replies'], True)} (p50 {f(s['reply_words_p50'])} words) |",
        f"| Agent turn time p50 / p95 (LLM + tools, no audio) | {f(s['agent_turn_ms_p50'])} / {f(s['agent_turn_ms_p95'])} ms |",
        f"| Agent LLM cost per call | ₹{s['llm_cost_inr_per_call']} |",
        "",
        "| Persona | Pass | Failed checks |",
        "|---|---|---|",
    ]
    by: dict[str, list[dict]] = {}
    for r in results:
        by.setdefault(r["persona"], []).append(r)
    for pid, rs in by.items():
        failed = sorted({k for r in rs for k, v in r["checks"].items() if not v}
                        | {v["criterion"] for r in rs for v in r["judge"] if not v["pass"]}
                        | {f"error: {r['error'][:60]}" for r in rs if r["error"]})
        rows.append(f"| {pid} | {sum(r['passed'] for r in rs)}/{len(rs)} | {'; '.join(failed)[:200] or '—'} |")
    return "\n".join(rows) + "\n"


if __name__ == "__main__":
    asyncio.run(main())
