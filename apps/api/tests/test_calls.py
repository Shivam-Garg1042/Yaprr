from datetime import datetime, timedelta, timezone

from tests.conftest import W


def _call(aid, cid="c1", outcome="promise_to_pay", interrupted=(True, False), version=1, days_ago=0):
    started = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return {
        "id": cid, "agent_id": aid, "agent_version": version, "room_name": "test-room",
        "started_at": started, "duration_s": 120, "ended_by": "user_initiated",
        "metrics": {"latency": {"response": {"p50_ms": 1200, "p95_ms": 2400}, "llm_ttft": {"p50_ms": 360}},
                    "cost": {"inr_total": 9.0, "inr_per_minute": 4.5}, "usage": {"llm_failovers": 1 if cid == "c0" else 0}},
        "dispositions": {"answers": {"call_outcome": outcome}},
        "transcript": [{"role": "agent", "text": "a", "interrupted": i} for i in interrupted]
                      + [{"role": "driver", "text": "d"}],
    }


def test_ingest_upsert_and_read(client):
    aid = client.get("/api/agents").json()[0]["id"]
    first = _call(aid)
    first["dispositions"] = {"answers": None, "status": "pending"}
    assert client.post("/api/internal/calls", json=first, headers=W).status_code == 201
    assert client.get("/api/calls/c1").json()["outcome"] is None
    client.post("/api/internal/calls", json=_call(aid), headers=W)  # dispositions arrive later
    c = client.get("/api/calls/c1").json()
    assert c["outcome"] == "promise_to_pay" and c["interrupt_rate"] == 0.5 and c["llm_ttft_p50_ms"] == 360
    assert client.get("/api/calls").json()["total"] == 1


def test_ingest_requires_token_and_tolerates_unknown_agent(client):
    assert client.post("/api/internal/calls", json=_call("nope")).status_code == 401
    assert client.post("/api/internal/calls", json=_call("nope", cid="c9"), headers=W).status_code == 201
    assert client.get("/api/calls/c9").json()["agent_id"] is None


def test_overview_stats(client):
    aid = client.get("/api/agents").json()[0]["id"]
    for i, o in enumerate(["promise_to_pay", "refused", "promise_to_pay"]):
        client.post("/api/internal/calls", json=_call(aid, cid=f"c{i}", outcome=o), headers=W)
    s = client.get("/api/stats/overview?days=365").json()["totals"]
    assert s["calls"] == 3 and s["outcomes"] == {"promise_to_pay": 2, "refused": 1}
    assert s["cost_inr_total"] == 27.0 and s["interrupt_rate"] == 0.5
    agent = client.get(f"/api/agents/{aid}").json()
    assert agent["stats"]["calls"] == 3


def test_filters_and_pagination(client):
    agents = client.get("/api/agents").json()
    a1, a2 = agents[0]["id"], agents[1]["id"]
    client.post("/api/internal/calls", json=_call(a1, cid="x1", outcome="refused", version=1), headers=W)
    client.post("/api/internal/calls", json=_call(a1, cid="x2", outcome="promise_to_pay", version=2), headers=W)
    client.post("/api/internal/calls", json=_call(a2, cid="x3", outcome="interested", days_ago=20), headers=W)
    assert client.get(f"/api/calls?agent_id={a1}").json()["total"] == 2
    assert client.get(f"/api/calls?agent_id={a1}&version=2").json()["items"][0]["id"] == "x2"
    assert client.get("/api/calls?outcome=refused").json()["total"] == 1
    assert client.get("/api/calls?days=7").json()["total"] == 2
    page = client.get("/api/calls?limit=1&offset=1").json()
    assert page["total"] == 3 and len(page["items"]) == 1
    ov = client.get("/api/stats/overview?days=30").json()
    assert {r["agent_id"] for r in ov["by_agent"]} == {a1, a2}
    assert [(r["version"], r["calls"]) for r in ov["by_version"] if r["agent_id"] == a1] == [(1, 1), (2, 1)]
    assert client.get(f"/api/stats/overview?agent_id={a2}").json()["totals"]["calls"] == 0  # 20 days ago, default 14d


def test_failover_rate(client):
    aid = client.get("/api/agents").json()[0]["id"]
    for i in range(2):
        client.post("/api/internal/calls", json=_call(aid, cid=f"c{i}"), headers=W)
    assert client.get("/api/stats/overview").json()["totals"]["failover_rate"] == 0.5
