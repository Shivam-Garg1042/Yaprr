"""Database tables.

Agent        - editable draft config (what the UI edits)
AgentVersion - immutable snapshot created on publish (what calls run, what evals compare)
Call         - one row per call: headline numbers as columns (fast dashboards),
               full metrics / transcript / dispositions as JSON.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from yaprr_api.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id() -> str:
    return uuid.uuid4().hex[:12]


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | live | paused | archived
    config: Mapped[dict] = mapped_column(JSON)  # draft AgentConfig
    published_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    versions: Mapped[list[AgentVersion]] = relationship(back_populates="agent", order_by="AgentVersion.version")


class AgentVersion(Base):
    __tablename__ = "agent_versions"
    __table_args__ = (UniqueConstraint("agent_id", "version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict] = mapped_column(JSON)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    agent: Mapped[Agent] = relationship(back_populates="versions")


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # set by the worker
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), index=True, nullable=True)
    agent_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    room_name: Mapped[str] = mapped_column(String(128))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_s: Mapped[float] = mapped_column(Float, default=0)
    ended_by: Mapped[str] = mapped_column(String(48), default="unknown")

    # headline numbers (denormalised for dashboards)
    response_p50_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    response_p95_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    llm_ttft_p50_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_inr: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_inr_per_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    agent_turns: Mapped[int] = mapped_column(Integer, default=0)
    interrupted_turns: Mapped[int] = mapped_column(Integer, default=0)
    outcome: Mapped[str | None] = mapped_column(String(48), nullable=True, index=True)
    llm_failovers: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # full detail
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    pipeline: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    dispositions: Mapped[dict] = mapped_column(JSON, default=dict)
    tool_calls: Mapped[list] = mapped_column(JSON, default=list)
    transcript: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
