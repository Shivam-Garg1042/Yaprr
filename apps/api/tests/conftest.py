import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ["WORKER_TOKEN"] = "t"
os.environ["LIVEKIT_URL"] = "wss://example.livekit.cloud"
os.environ["LIVEKIT_API_KEY"] = "devkey"
os.environ["LIVEKIT_API_SECRET"] = "devsecret-devsecret-devsecret-devsecret"

import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from yaprr_api.db import Base, engine  # noqa: E402
from yaprr_api.main import app  # noqa: E402

W = {"X-Worker-Token": "t"}


def _reset():
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


@pytest.fixture()
def client():
    _reset()
    with TestClient(app) as c:  # runs lifespan: alembic upgrade + seed demo agents
        yield c
    _reset()
