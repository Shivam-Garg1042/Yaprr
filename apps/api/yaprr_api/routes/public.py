"""Public demo: anyone can talk to one agent, inside hard spend caps.

Every demo call costs real money (STT + LLM + TTS, roughly ₹3/min), so a public
"try it" button is a cost-attack surface. Three limits, checked before a token
is minted:

1. Call length: the worker hangs up at `demo_max_call_seconds`. The limit is
   signed into the LiveKit token, so the browser can't raise it.
2. Per visitor: `demo_calls_per_ip_per_day` calls per IP in a rolling 24 h.
   Best effort (people share IPs, VPNs exist), so it's not the real wall.
3. Global: `demo_minutes_per_day` minutes in a rolling 24 h. Each call reserves
   its full maximum length up front, so the worst case per day is known:
   minutes x ~₹3. This is the hard cap.

The token's TTL is short, so a stolen token can't be reused to open new rooms later.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from yaprr_api.db import get_db
from yaprr_api.models import Agent, DemoSession
from yaprr_api.routes.agents import mint_session
from yaprr_api.schemas import AgentConfig, TestSessionOut
from yaprr_api.seed import DEMO_AGENTS
from yaprr_api.settings import get_settings

router = APIRouter(prefix="/api/public", tags=["public"])

WINDOW = timedelta(hours=24)


def client_ip(request: Request) -> str:
    """The visitor's IP behind Netlify -> Lambda. Netlify sets x-nf-client-connection-ip;
    otherwise the first X-Forwarded-For hop; otherwise the socket peer."""
    h = request.headers
    ip = h.get("x-nf-client-connection-ip") or (h.get("x-forwarded-for") or "").split(",")[0].strip()
    return ip or (request.client.host if request.client else "unknown")


def _hash(ip: str) -> str:
    # Salted with a server secret so the table can't be reversed into IPs.
    return hashlib.sha256(f"{get_settings().worker_token}:{ip}".encode()).hexdigest()


def demo_agent(db: Session) -> Agent | None:
    s = get_settings()
    if s.demo_agent_id:
        return db.get(Agent, s.demo_agent_id)
    return db.scalar(select(Agent).where(Agent.name == DEMO_AGENTS[0]["name"], Agent.published_version.is_not(None))
                     .order_by(Agent.created_at))


def _usage(db: Session, ip_hash: str) -> tuple[int, int]:
    since = datetime.now(timezone.utc) - WINDOW
    mine = db.scalar(select(func.count(DemoSession.id)).where(DemoSession.ip_hash == ip_hash,
                                                              DemoSession.created_at >= since)) or 0
    seconds = db.scalar(select(func.coalesce(func.sum(DemoSession.seconds_reserved), 0))
                        .where(DemoSession.created_at >= since)) or 0
    return int(mine), int(seconds)


def _limits(db: Session, request: Request) -> dict:
    s = get_settings()
    mine, seconds = _usage(db, _hash(client_ip(request)))
    return {
        "max_call_seconds": s.demo_max_call_seconds,
        "calls_per_day": s.demo_calls_per_ip_per_day,
        "calls_left": max(0, s.demo_calls_per_ip_per_day - mine),
        "minutes_left_today": max(0, s.demo_minutes_per_day * 60 - seconds) // 60,
    }


@router.get("/demo")
def demo_info(request: Request, db: Session = Depends(get_db)) -> dict:
    """What the /try page shows before the visitor presses Start."""
    s = get_settings()
    agent = demo_agent(db) if s.demo_enabled else None
    if not agent:
        return {"enabled": False, "public_read": s.public_read}
    cfg = AgentConfig.model_validate(agent.config)
    return {"enabled": True, "public_read": s.public_read, "agent": {
        "name": agent.name, "persona": cfg.persona_name, "use_case": cfg.use_case, "language": cfg.language,
        "version": agent.published_version}, "limits": _limits(db, request)}


@router.post("/demo-session", response_model=TestSessionOut)
def demo_session(request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    agent = demo_agent(db) if s.demo_enabled else None
    if not agent or agent.published_version is None:
        raise HTTPException(404, "the public demo is off")
    ip_hash = _hash(client_ip(request))
    mine, seconds = _usage(db, ip_hash)
    if mine >= s.demo_calls_per_ip_per_day:
        raise HTTPException(429, f"You've used your {s.demo_calls_per_ip_per_day} demo calls for today. Try again tomorrow.")
    if seconds + s.demo_max_call_seconds > s.demo_minutes_per_day * 60:
        raise HTTPException(429, "Today's demo minutes are used up. Try again tomorrow.")
    session = mint_session(agent, agent.published_version, room_prefix="demo",
                           max_call_seconds=s.demo_max_call_seconds, ttl=timedelta(minutes=2))
    db.add(DemoSession(ip_hash=ip_hash, room_name=session.room_name, seconds_reserved=s.demo_max_call_seconds))
    db.commit()
    return session
