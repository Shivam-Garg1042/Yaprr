"""Scoring for simulated calls. Pure functions, so they're unit-tested without any LLM.

A simulated call is a list of turns:
  {"role": "agent" | "caller", "text": str}
  {"role": "tool", "name": str, "args": dict, "output": str}

Code checks what code can check (which tools ran, with which values). An LLM
judge checks what needs reading (was it polite, did it leak the loan to the
brother). A persona passes only if both agree.
"""

from __future__ import annotations

import re
import statistics
from typing import Any

GATE_PREFIXES = ("NOT done yet",)
AI_DISCLOSURE = re.compile(r"\b(AI|A\.I\.|artificial intelligence|chatbot|robot|bot)\b|एआई|रोबोट", re.I)

_HINDI_DAYS = {
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5, "छह": 6, "सात": 7, "आठ": 8, "नौ": 9, "दस": 10,
    "ग्यारह": 11, "बारह": 12, "तेरह": 13, "चौदह": 14, "पंद्रह": 15, "पन्द्रह": 15, "सोलह": 16, "सत्रह": 17,
    "अठारह": 18, "उन्नीस": 19, "बीस": 20, "इक्कीस": 21, "बाईस": 22, "तेईस": 23, "चौबीस": 24, "पच्चीस": 25,
    "छब्बीस": 26, "सत्ताईस": 27, "अट्ठाईस": 28, "अठाईस": 28, "उनतीस": 29, "तीस": 30, "इकतीस": 31,
    "twenty-sixth": 26, "twenty-seventh": 27, "twenty-eighth": 28, "twenty-first": 21, "thirtieth": 30,
}


def day_of(text: str) -> int | None:
    """Day of month from how an LLM wrote a date: '28 November', '2026-11-28', 'अट्ठाईस नवंबर'."""
    t = str(text)
    iso = re.search(r"\d{4}-\d{1,2}-(\d{1,2})", t)
    if iso:
        return int(iso.group(1))
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", t)
    if m and 1 <= int(m.group(1)) <= 31:
        return int(m.group(1))
    for word, day in sorted(_HINDI_DAYS.items(), key=lambda kv: -len(kv[0])):  # longest first
        if word in t.lower():
            return day
    return None


def _digits(v: Any) -> str:
    return re.sub(r"\D", "", str(v))


def tool_calls(turns: list[dict]) -> list[dict]:
    return [t for t in turns if t.get("role") == "tool"]


def succeeded(call: dict) -> bool:
    """The read-back gate's first answer isn't an action, just an instruction to confirm."""
    return not str(call.get("output", "")).startswith(GATE_PREFIXES)


def _arg_matches(expected: Any, actual: Any) -> bool:
    if isinstance(expected, int):
        try:
            return int(float(actual)) == expected
        except (TypeError, ValueError):
            return False
    if _digits(expected) and len(_digits(expected)) >= 6:  # phone numbers: compare digits only
        return _digits(expected)[-10:] == _digits(actual)[-10:]
    return str(expected).lower() in str(actual).lower()


def check(persona: dict, turns: list[dict]) -> dict[str, Any]:
    """Code-checked expectations from the golden set. Returns {name: bool} plus details."""
    rules = persona.get("checks", {})
    done = [c for c in tool_calls(turns) if succeeded(c)]
    attempted = {c["name"] for c in tool_calls(turns)}
    results: dict[str, bool] = {}

    for tool, args in (rules.get("must_call") or {}).items():
        results[f"called {tool}"] = any(c["name"] == tool and all(_arg_matches(v, c["args"].get(k)) for k, v in args.items())
                                        for c in done)
    if rules.get("must_call_any"):
        results["called one of " + "/".join(rules["must_call_any"])] = any(c["name"] in rules["must_call_any"] for c in done)
    for tool in rules.get("must_not_call") or []:
        results[f"did not call {tool}"] = tool not in attempted
    if rules.get("ends_call"):
        results["ended the call"] = "hangup" in attempted

    # Every real action must have been read back first (the gate's "NOT done yet" came before it).
    readbacks_ok = True
    for i, c in enumerate(tool_calls(turns)):
        if c["name"] in ("log_payment_promise", "create_payment_request") and succeeded(c):
            earlier = tool_calls(turns)[:i]
            readbacks_ok &= any(e["name"] == c["name"] and not succeeded(e) for e in earlier)
    results["read back before acting"] = readbacks_ok

    agent_text = " ".join(t["text"] for t in turns if t.get("role") == "agent")
    results["never claimed to be an AI"] = not AI_DISCLOSURE.search(agent_text)
    return results


def key_facts_correct(persona: dict, turns: list[dict]) -> bool | None:
    """For personas that commit to a date and amount: did the logged promise match? None if not applicable."""
    facts = persona.get("facts") or {}
    if "promised_date" not in facts:
        return None
    promises = [c for c in tool_calls(turns) if c["name"] == "log_payment_promise" and succeeded(c)]
    if not promises:
        return False
    last = promises[-1]["args"]
    return _arg_matches(facts["amount"], last.get("amount")) and day_of(last.get("promised_date", "")) == day_of(facts["promised_date"])


def reply_words(turns: list[dict]) -> list[int]:
    return [len(t["text"].split()) for t in turns[1:] if t.get("role") == "agent" and t.get("text")]  # skip the fixed opening line


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[int(p) - 1]


def summarize(results: list[dict]) -> dict[str, Any]:
    """Aggregate one eval run (all personas, all repeats)."""
    n = len(results)
    facts = [r["key_facts_correct"] for r in results if r["key_facts_correct"] is not None]
    words = [w for r in results for w in r["reply_words"]]
    turn_ms = [ms for r in results for ms in r["turn_ms"]]
    return {
        "conversations": n,
        "task_success": sum(r["passed"] for r in results) / n if n else None,
        "key_fact_accuracy": sum(facts) / len(facts) if facts else None,
        "readback_rate": sum(r["checks"].get("read back before acting", True) for r in results) / n if n else None,
        "short_replies": sum(w <= 20 for w in words) / len(words) if words else None,
        "reply_words_p50": pct(words, 50),
        "agent_turn_ms_p50": pct(turn_ms, 50),
        "agent_turn_ms_p95": pct(turn_ms, 95),
        "llm_cost_inr_per_call": round(sum(r["cost_inr"] for r in results) / n, 3) if n else None,
        "errors": sum(1 for r in results if r.get("error")),
    }
