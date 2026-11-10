"""yaprr API.

    uvicorn yaprr_api.main:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from yaprr_api.db import Base, SessionLocal, add_missing_columns, engine
from yaprr_api.routes import agents, calls
from yaprr_api.seed import seed_demo_agents
from yaprr_api.settings import get_settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    # M1: create tables directly. Alembic migrations come once the schema settles.
    Base.metadata.create_all(engine)
    add_missing_columns(engine)
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
app.include_router(agents.router)
app.include_router(calls.router)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}
