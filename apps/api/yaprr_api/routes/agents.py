from __future__ import annotations

import json
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from yaprr_api.db import get_db
from yaprr_api.deps import require_admin, require_read, require_worker
from yaprr_api.models import Agent, AgentVersion, Call
from yaprr_api.schemas import (
    TOOL_CATALOG,
    AgentConfig,
    AgentCreate,
    AgentOut,
    AgentUpdate,
    PublishIn,
    RuntimeConfigOut,
    TestSessionIn,
    TestSessionOut,
    VersionOut,
)
from yaprr_api.seed import DEMO_CONTEXT
from yaprr_api.settings import get_settings
from yaprr_api.stats import summarize

router = APIRouter(prefix="/api", tags=["agents"], dependencies=[Depends(require_admin)])
# GETs: also open to visitors when PUBLIC_READ is on (see deps.require_read).
read = APIRouter(prefix="/api", tags=["agents"], dependencies=[Depends(require_read)])
internal = APIRouter(prefix="/api", tags=["internal"], dependencies=[Depends(require_worker)])


def _get(db: Session, agent_id: str) -> Agent:
    agent = db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "agent not found")
    return agent


def _out(db: Session, agent: Agent, with_stats: bool = True) -> AgentOut:
    stats = summarize(db.scalars(select(Call).where(Call.agent_id == agent.id))) if with_stats else {}
    return AgentOut(
        id=agent.id, name=agent.name, status=agent.status, config=AgentConfig.model_validate(agent.config),
        published_version=agent.published_version, created_at=agent.created_at, updated_at=agent.updated_at,
        stats=stats,
    )


@read.get("/tools")
def list_tools() -> dict[str, str]:
    return TOOL_CATALOG


@read.get("/agents", response_model=list[AgentOut])
def list_agents(include_archived: bool = False, db: Session = Depends(get_db)):
    q = select(Agent).order_by(Agent.created_at)
    if not include_archived:
        q = q.where(Agent.status != "archived")
    return [_out(db, a) for a in db.scalars(q)]


@router.post("/agents", response_model=AgentOut, status_code=201)
def create_agent(body: AgentCreate, db: Session = Depends(get_db)):
    agent = Agent(name=body.name, status="draft", config=body.config.model_dump())
    db.add(agent)
    db.commit()
    return _out(db, agent)


@read.get("/agents/{agent_id}", response_model=AgentOut)
def get_agent(agent_id: str, db: Session = Depends(get_db)):
    return _out(db, _get(db, agent_id))


@router.patch("/agents/{agent_id}", response_model=AgentOut)
def update_agent(agent_id: str, body: AgentUpdate, db: Session = Depends(get_db)):
    agent = _get(db, agent_id)
    if body.name is not None:
        agent.name = body.name
    if body.config is not None:
        agent.config = body.config.model_dump()
    if body.status is not None:
        if body.status == "live" and agent.published_version is None:
            raise HTTPException(409, "publish a version before going live")
        agent.status = body.status
    db.commit()
    return _out(db, agent)


@router.delete("/agents/{agent_id}", status_code=204)
def archive_agent(agent_id: str, db: Session = Depends(get_db)):
    """Soft delete: calls keep pointing at the agent."""
    _get(db, agent_id).status = "archived"
    db.commit()


@router.post("/agents/{agent_id}/duplicate", response_model=AgentOut, status_code=201)
def duplicate_agent(agent_id: str, db: Session = Depends(get_db)):
    """Copy an agent's draft into a new draft agent: the fastest way to A/B a script."""
    src = _get(db, agent_id)
    copy = Agent(name=f"{src.name} (copy)"[:120], status="draft", config=dict(src.config))
    db.add(copy)
    db.commit()
    return _out(db, copy)


@router.post("/agents/{agent_id}/publish", response_model=VersionOut, status_code=201)
def publish_agent(agent_id: str, body: PublishIn, db: Session = Depends(get_db)):
    """Freeze the current draft as an immutable version. Calls and evals reference versions."""
    agent = _get(db, agent_id)
    latest = db.scalar(select(AgentVersion).where(AgentVersion.agent_id == agent_id).order_by(AgentVersion.version.desc()))
    if latest and latest.config == agent.config:
        raise HTTPException(409, f"no changes since v{latest.version}")
    version = (latest.version if latest else 0) + 1
    v = AgentVersion(agent_id=agent_id, version=version, config=agent.config, note=body.note)
    db.add(v)
    agent.published_version = version
    if agent.status == "draft":
        agent.status = "live"
    db.commit()
    return VersionOut(version=v.version, note=v.note, created_at=v.created_at, config=AgentConfig.model_validate(v.config))


@read.get("/agents/{agent_id}/versions", response_model=list[VersionOut])
def list_versions(agent_id: str, db: Session = Depends(get_db)):
    _get(db, agent_id)
    rows = db.scalars(select(AgentVersion).where(AgentVersion.agent_id == agent_id).order_by(AgentVersion.version.desc()))
    return [VersionOut(version=v.version, note=v.note, created_at=v.created_at,
                       config=AgentConfig.model_validate(v.config)) for v in rows]


@internal.get("/internal/agents/{agent_id}/runtime", response_model=RuntimeConfigOut)
def runtime_config(agent_id: str, version: int | None = None, draft: bool = False, db: Session = Depends(get_db)):
    """What the worker runs. Default: latest published version. `draft=true` for test calls."""
    agent = _get(db, agent_id)
    if draft:
        return RuntimeConfigOut(agent_id=agent.id, name=agent.name, version=0,
                                config=AgentConfig.model_validate(agent.config))
    version = version or agent.published_version
    if version is None:
        raise HTTPException(409, "agent has no published version")
    v = db.scalar(select(AgentVersion).where(AgentVersion.agent_id == agent_id, AgentVersion.version == version))
    if not v:
        raise HTTPException(404, f"version {version} not found")
    return RuntimeConfigOut(agent_id=agent.id, name=agent.name, version=v.version,
                            config=AgentConfig.model_validate(v.config))


@router.post("/agents/{agent_id}/test-session", response_model=TestSessionOut)
def test_session(agent_id: str, body: TestSessionIn, db: Session = Depends(get_db)):
    """Browser "Talk to agent": a LiveKit token whose room auto-dispatches our worker
    with {agent_id, version, context} as job metadata."""
    agent = _get(db, agent_id)
    version = None if body.use_draft else (body.version or agent.published_version)
    if not body.use_draft and version is None:
        raise HTTPException(409, "publish first, or set use_draft=true")
    return mint_session(agent, version, draft=body.use_draft, context=body.context, room_prefix="test")


def mint_session(agent: Agent, version: int | None, *, draft: bool = False, context: dict[str, str] | None = None,
                 room_prefix: str = "test", max_call_seconds: int | None = None,
                 ttl: timedelta = timedelta(minutes=30)) -> TestSessionOut:
    """A LiveKit token for a fresh room that dispatches our worker. Everything in the
    metadata is signed into the token, so the browser can't change the agent or the limits."""
    from livekit import api

    s = get_settings()
    if not (s.livekit_url and s.livekit_api_key and s.livekit_api_secret):
        raise HTTPException(503, "LiveKit is not configured on the API (LIVEKIT_URL/API_KEY/API_SECRET)")
    cfg = AgentConfig.model_validate(agent.config)
    ctx = {k: v for k, v in DEMO_CONTEXT.items() if k in cfg.variables} | (context or {})
    ctx.setdefault("persona_name", cfg.persona_name)
    room = f"{room_prefix}-{agent.id}-{uuid.uuid4().hex[:6]}"
    meta = {"agent_id": agent.id, "version": version, "draft": draft, "context": ctx}
    if max_call_seconds:
        meta["max_call_seconds"] = max_call_seconds
    token = (
        api.AccessToken(s.livekit_api_key, s.livekit_api_secret)
        .with_identity(f"{room_prefix}er-{uuid.uuid4().hex[:6]}")
        .with_name(f"yaprr {room_prefix}")
        .with_ttl(ttl)
        .with_grants(api.VideoGrants(room_join=True, room=room))
        .with_room_config(api.RoomConfiguration(
            agents=[api.RoomAgentDispatch(agent_name=s.worker_agent_name,
                                          metadata=json.dumps(meta, ensure_ascii=False))]))
        .to_jwt()
    )
    return TestSessionOut(livekit_url=s.livekit_url, token=token, room_name=room, agent_version=version)
