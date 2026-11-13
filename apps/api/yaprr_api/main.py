"""yaprr API.

    uvicorn yaprr_api.main:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from yaprr_api.db import SessionLocal, migrate
from yaprr_api.routes import agents, calls
from yaprr_api.seed import seed_demo_agents
from yaprr_api.settings import get_settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    migrate()  # Alembic: schema changes are versioned migrations in apps/api/migrations/versions
    if get_settings().seed_demo_agents:
        with SessionLocal() as db:
            seed_demo_agents(db)
    yield


app = FastAPI(title="yaprr API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)
# Routers carry their own auth: dashboard endpoints need the admin token,
# /api/internal/* need the worker token (see deps.py).
app.include_router(agents.router)
app.include_router(agents.internal)
app.include_router(calls.router)
app.include_router(calls.internal)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}
