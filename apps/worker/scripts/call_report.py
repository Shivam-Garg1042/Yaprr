"""Aggregate runtime/calls/*.json into one report (latency, cost, outcomes).

    python scripts/call_report.py                 # all calls
    python scripts/call_report.py --since 20261104 # calls from that day on (file-name prefix)

Use it for before/after comparisons when you change a latency knob.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.call_metrics import percentile  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="runtime/calls")
    ap.add_argument("--since", default="")
    args = ap.parse_args()

    files = sorted(p for p in Path(args.dir).glob("*.json") if p.name >= args.since)
    if not files:
        print(f"No call records in {args.dir}")
        return
    recs = [json.loads(p.read_text(encoding="utf-8")) for p in files]

    p50s = [r["metrics"]["latency"]["response"]["p50_ms"] for r in recs if r["metrics"]["latency"]["response"]["p50_ms"]]
    p95s = [r["metrics"]["latency"]["response"]["p95_ms"] for r in recs if r["metrics"]["latency"]["response"]["p95_ms"]]
    ttft = [r["metrics"]["latency"]["llm_ttft"]["p50_ms"] for r in recs if r["metrics"]["latency"]["llm_ttft"]["p50_ms"]]
    ttfb = [r["metrics"]["latency"]["tts_ttfb"]["p50_ms"] for r in recs if r["metrics"]["latency"]["tts_ttfb"]["p50_ms"]]
    eou = [r["metrics"]["latency"]["end_of_utterance"]["p50_ms"] for r in recs if r["metrics"]["latency"]["end_of_utterance"]["p50_ms"]]
    cost = [r["metrics"]["cost"]["inr_total"] for r in recs]
    cpm = [r["metrics"]["cost"]["inr_per_minute"] for r in recs if r["metrics"]["cost"]["inr_per_minute"]]
    dur = [r["duration_s"] for r in recs]
    outcomes = Counter(((r.get("dispositions") or {}).get("answers") or {}).get("call_outcome", "n/a") for r in recs)
    ended = Counter(r.get("ended_by", "unknown") for r in recs)

    med = lambda xs: percentile(xs, 50)  # noqa: E731
    print(f"Calls: {len(recs)}  |  median duration: {med(dur)}s")
    print(f"Response latency  median-of-p50: {med(p50s)} ms   median-of-p95: {med(p95s)} ms")
    print(f"  breakdown (median p50): EOU {med(eou)} ms | LLM TTFT {med(ttft)} ms | TTS TTFB {med(ttfb)} ms")
    print(f"Cost: median ₹{med(cost)}/call, ₹{med(cpm)}/min, total ₹{round(sum(cost), 2)}")
    print("Outcomes:", dict(outcomes.most_common()))
    print("Ended by:", dict(ended.most_common()))


if __name__ == "__main__":
    main()
