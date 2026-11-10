"""Aggregations over calls. Done in Python (not SQL percentiles) so the same code
runs on Postgres and SQLite; fine up to tens of thousands of calls."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from typing import Any

from yaprr_api.models import Call


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(1, math.ceil(pct / 100 * len(ordered))) - 1]


def interrupt_rate(call: Call) -> float | None:
    return round(call.interrupted_turns / call.agent_turns, 3) if call.agent_turns else None


def summarize(calls: Iterable[Call]) -> dict[str, Any]:
    calls = list(calls)
    resp = [c.response_p50_ms for c in calls if c.response_p50_ms is not None]
    resp95 = [c.response_p95_ms for c in calls if c.response_p95_ms is not None]
    ttft = [c.llm_ttft_p50_ms for c in calls if c.llm_ttft_p50_ms is not None]
    cpm = [c.cost_inr_per_min for c in calls if c.cost_inr_per_min is not None]
    turns = sum(c.agent_turns for c in calls)
    minutes = sum(c.duration_s for c in calls) / 60
    connected = [c for c in calls if c.outcome and c.outcome != "no_conversation"]
    return {
        "calls": len(calls),
        "connected": len(connected),
        "minutes": round(minutes, 1),
        "response_p50_ms": percentile(resp, 50),
        "response_p95_ms": percentile(resp95, 95),
        "llm_ttft_p50_ms": percentile(ttft, 50),
        "cost_inr_total": round(sum(c.cost_inr or 0 for c in calls), 2),
        "cost_inr_per_min_p50": percentile(cpm, 50),
        "interrupt_rate": round(sum(c.interrupted_turns for c in calls) / turns, 3) if turns else None,
        "failover_rate": round(sum(1 for c in calls if (c.llm_failovers or 0) > 0) / len(calls), 3) if calls else None,
        "outcomes": dict(Counter(c.outcome or "pending" for c in calls).most_common()),
    }
