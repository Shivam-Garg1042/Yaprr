import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ["WORKER_TOKEN"] = "t"
os.environ["LIVEKIT_URL"] = "wss://example.livekit.cloud"
os.environ["LIVEKIT_API_KEY"] = "devkey"
os.environ["LIVEKIT_API_SECRET"] = "devsecret-devsecret-devsecret-devsecret"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from yaprr_api.db import Base, engine  # noqa: E402
from yaprr_api.main import app  # noqa: E402

W = {"X-Worker-Token": "t"}


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    with TestClient(app) as c:  # runs lifespan: create tables + seed demo agents
        yield c
    Base.metadata.drop_all(engine)
