from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from yaprr_api.db import get_db
from yaprr_api.deps import require_admin, require_worker
from yaprr_api.models import Agent, Call
from yaprr_api.schemas import CallIn, CallOut, CallPage
from yaprr_api.stats import interrupt_rate, summarize

router = APIRouter(prefix="/api", tags=["calls"], dependencies=[Depends(require_admin)])
internal = APIRouter(prefix="/api", tags=["internal"], dependencies=[Depends(require_worker)])


def _summary(c: Call) -> dict:
    return {
        "id": c.id, "agent_id": c.agent_id, "agent_version": c.agent_version, "room_name": c.room_name,
        "started_at": c.started_at, "duration_s": c.duration_s, "ended_by": c.ended_by, "outcome": c.outcome,
        "response_p50_ms": c.response_p50_ms, "response_p95_ms": c.response_p95_ms,
        "llm_ttft_p50_ms": c.llm_ttft_p50_ms, "cost_inr": c.cost_inr, "cost_inr_per_min": c.cost_inr_per_min,
        "interrupt_rate": interrupt_rate(c), "llm_failovers": c.llm_failovers,
    }


class CallFilters:
    """Shared by the calls list and the stats endpoints, so a dashboard and its
    table always show the same set of calls."""

    def __init__(
        self,
        agent_id: str | None = None,
        version: int | None = Query(None, ge=0),
        outcome: str | None = None,
        ended_by: str | None = None,
        days: int | None = Query(None, ge=1, le=365, description="last N days"),
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ):
        self.agent_id, self.version, self.outcome, self.ended_by = agent_id, version, outcome, ended_by
        self.date_from = date_from or (datetime.now(timezone.utc) - timedelta(days=days) if days else None)
        self.date_to = date_to

    def apply(self, q: Select) -> Select:
        if self.agent_id:
            q = q.where(Call.agent_id == self.agent_id)
        if self.version is not None:
            q = q.where(Call.agent_version == self.version)
        if self.outcome:
            q = q.where(Call.outcome.is_(None)) if self.outcome == "pending" else q.where(Call.outcome == self.outcome)
        if self.ended_by:
            q = q.where(Call.ended_by == self.ended_by)
        if self.date_from:
            q = q.where(Call.started_at >= self.date_from)
        if self.date_to:
            q = q.where(Call.started_at < self.date_to)
        return q


@internal.post("/internal/calls", status_code=201)
def ingest_call(body: CallIn, db: Session = Depends(get_db)) -> dict:
    """Upsert: the worker posts once when the call ends, again when dispositions finish."""
    if body.agent_id and not db.get(Agent, body.agent_id):
        body.agent_id = None  # console/dev calls without a DB agent still get stored
    call = db.get(Call, body.id) or Call(id=body.id)
    for field, value in body.model_dump().items():
        setattr(call, field, value)
    lat = body.metrics.get("latency", {})
    cost = body.metrics.get("cost", {})
    call.response_p50_ms = lat.get("response", {}).get("p50_ms")
    call.response_p95_ms = lat.get("response", {}).get("p95_ms")
    call.llm_ttft_p50_ms = lat.get("llm_ttft", {}).get("p50_ms")
    call.cost_inr = cost.get("inr_total")
    call.cost_inr_per_min = cost.get("inr_per_minute")
    call.llm_failovers = body.metrics.get("usage", {}).get("llm_failovers")
    agent_msgs = [t for t in body.transcript if t.get("role") == "agent"]
    call.agent_turns = len(agent_msgs)
    call.interrupted_turns = sum(1 for t in agent_msgs if t.get("interrupted"))
    answers = (body.dispositions or {}).get("answers") or {}
    call.outcome = answers.get("call_outcome")
    db.add(call)
    db.commit()
    return {"id": call.id}


@router.get("/calls", response_model=CallPage)
def list_calls(f: CallFilters = Depends(), limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
               db: Session = Depends(get_db)):
    total = db.scalar(f.apply(select(func.count(Call.id))))
    rows = db.scalars(f.apply(select(Call)).order_by(Call.started_at.desc()).limit(limit).offset(offset))
    return {"items": [_summary(c) for c in rows], "total": total or 0, "limit": limit, "offset": offset}


@router.get("/calls/{call_id}", response_model=CallOut)
def get_call(call_id: str, db: Session = Depends(get_db)):
    c = db.get(Call, call_id)
    if not c:
        raise HTTPException(404, "call not found")
    return {**_summary(c), "context": c.context, "pipeline": c.pipeline, "metrics": c.metrics,
            "dispositions": c.dispositions, "tool_calls": c.tool_calls, "transcript": c.transcript}


@router.get("/stats/overview")
def overview(f: CallFilters = Depends(), db: Session = Depends(get_db)) -> dict:
    """Totals + daily series + breakdown by agent and by version, for the same filtered calls."""
    if not (f.date_from or f.date_to):
        f.date_from = datetime.now(timezone.utc) - timedelta(days=14)
    calls = list(db.scalars(f.apply(select(Call))))
    names = dict(db.execute(select(Agent.id, Agent.name)).all())

    def group(key) -> dict:
        out: dict = {}
        for c in calls:
            out.setdefault(key(c), []).append(c)
        return out

    return {
        "filters": {"agent_id": f.agent_id, "version": f.version, "outcome": f.outcome,
                    "date_from": f.date_from, "date_to": f.date_to},
        "totals": summarize(calls),
        "daily": [{"day": d, **summarize(cs)} for d, cs in sorted(group(lambda c: c.started_at.date().isoformat()).items())],
        "by_agent": [{"agent_id": a, "name": names.get(a, "(no agent)"), **summarize(cs)}
                     for a, cs in group(lambda c: c.agent_id).items()],
        "by_version": [{"agent_id": a, "version": v, **summarize(cs)}
                       for (a, v), cs in sorted(group(lambda c: (c.agent_id, c.agent_version)).items(),
                                                key=lambda kv: (str(kv[0][0]), kv[0][1] or 0))],
    }
