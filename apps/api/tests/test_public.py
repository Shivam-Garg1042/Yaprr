import json

import pytest
from livekit import api

from tests.conftest import W
from tests.test_calls import _call
from yaprr_api.settings import get_settings

ADMIN = {"Authorization": "Bearer s3cret"}


@pytest.fixture()
def locked(monkeypatch):
    """A deploy with an admin token, public read and the demo switched on."""
    s = get_settings()
    for k, v in {"admin_token": "s3cret", "public_read": True, "demo_enabled": True,
                 "demo_calls_per_ip_per_day": 2, "demo_minutes_per_day": 5, "demo_max_call_seconds": 120}.items():
        monkeypatch.setattr(s, k, v)
    return s


def _ip(ip):
    return {"x-nf-client-connection-ip": ip}


def test_demo_session_is_capped_per_ip_and_signs_the_call_limit(client, locked):
    info = client.get("/api/public/demo", headers=_ip("1.1.1.1")).json()
    assert info["enabled"] and info["agent"]["persona"] == "Neha" and info["limits"]["calls_left"] == 2

    out = client.post("/api/public/demo-session", headers=_ip("1.1.1.1")).json()
    claims = api.TokenVerifier("devkey", "devsecret-devsecret-devsecret-devsecret").verify(out["token"])
    meta = json.loads(claims.room_config.agents[0].metadata)
    assert meta["max_call_seconds"] == 120 and meta["version"] == 1 and out["room_name"].startswith("demo-")

    assert client.post("/api/public/demo-session", headers=_ip("1.1.1.1")).status_code == 200
    r = client.post("/api/public/demo-session", headers=_ip("1.1.1.1"))
    assert r.status_code == 429 and "demo calls" in r.json()["detail"]
    assert client.get("/api/public/demo", headers=_ip("1.1.1.1")).json()["limits"]["calls_left"] == 0


def test_daily_minutes_cap_is_global(client, locked):
    # 5 min/day, 2 min reserved per call -> only 2 calls fit, whoever asks.
    assert client.post("/api/public/demo-session", headers=_ip("1.0.0.1")).status_code == 200
    assert client.post("/api/public/demo-session", headers=_ip("1.0.0.2")).status_code == 200
    r = client.post("/api/public/demo-session", headers=_ip("1.0.0.3"))
    assert r.status_code == 429 and "minutes" in r.json()["detail"]


def test_demo_off_by_default(client):
    assert client.get("/api/public/demo").json()["enabled"] is False
    assert client.post("/api/public/demo-session").status_code == 404


def test_public_read_is_read_only_and_can_hide_transcripts(client, locked, monkeypatch):
    monkeypatch.setattr(locked, "public_transcripts", False)
    aid = client.get("/api/agents").json()[0]["id"]  # visitors can browse
    body = _call(aid)
    body["dispositions"] = {"answers": {"call_outcome": "promise_to_pay", "summary": "Ramesh will pay on Friday"}}
    client.post("/api/internal/calls", json=body, headers=W)

    public = client.get("/api/calls/c1").json()
    assert public["redacted"] and public["transcript"] == [] and public["context"] == {}
    assert public["dispositions"]["answers"] == {"call_outcome": "promise_to_pay"}  # free text dropped
    assert client.get("/api/stats/overview").json()["totals"]["calls"] == 1

    full = client.get("/api/calls/c1", headers=ADMIN).json()
    assert not full["redacted"] and full["transcript"] and full["dispositions"]["answers"]["summary"]

    # anything that writes or costs money still needs the token
    assert client.post("/api/agents", json={"name": "x", "config": {}}).status_code == 401
    assert client.post(f"/api/agents/{aid}/test-session", json={}).status_code == 401
    assert client.post(f"/api/agents/{aid}/publish", json={}).status_code == 401


def test_without_public_read_visitors_get_nothing(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_token", "s3cret")
    assert client.get("/api/calls").status_code == 401
    assert client.get("/api/calls", headers=ADMIN).status_code == 200


def test_visitors_see_transcripts_by_default(client, locked):
    aid = client.get("/api/agents").json()[0]["id"]
    client.post("/api/internal/calls", json=_call(aid), headers=W)
    c = client.get("/api/calls/c1").json()
    assert not c["redacted"] and c["transcript"]
