import json

from livekit import api


from tests.conftest import W

MIN_CFG = {"prompt": "You are a polite assistant calling {customer_name} about a reminder.",
           "variables": ["customer_name"], "opening_line": "Hello {customer_name}!"}


def test_demo_agents_seeded_and_published(client):
    agents = client.get("/api/agents").json()
    assert [a["name"] for a in agents] == ["Neha · EMI reminder", "Khushi · Battery sales"]
    assert all(a["published_version"] == 1 and a["status"] == "live" for a in agents)


def test_create_edit_publish_flow(client):
    a = client.post("/api/agents", json={"name": "Test", "config": MIN_CFG}).json()
    assert a["status"] == "draft" and a["published_version"] is None
    # worker can't run an unpublished agent by default...
    assert client.get(f"/api/internal/agents/{a['id']}/runtime", headers=W).status_code == 409
    # ...but can run the draft for test calls
    assert client.get(f"/api/internal/agents/{a['id']}/runtime?draft=true", headers=W).json()["version"] == 0

    v1 = client.post(f"/api/agents/{a['id']}/publish", json={"note": "first"}).json()
    assert v1["version"] == 1
    assert client.post(f"/api/agents/{a['id']}/publish", json={}).status_code == 409  # nothing changed

    cfg2 = {**MIN_CFG, "prompt": MIN_CFG["prompt"] + " Be brief."}
    client.patch(f"/api/agents/{a['id']}", json={"config": cfg2})
    assert client.post(f"/api/agents/{a['id']}/publish", json={"note": "shorter"}).json()["version"] == 2
    rt = client.get(f"/api/internal/agents/{a['id']}/runtime?version=1", headers=W).json()
    assert rt["config"]["prompt"] == MIN_CFG["prompt"]  # v1 is immutable
    assert [v["version"] for v in client.get(f"/api/agents/{a['id']}/versions").json()] == [2, 1]


def test_validation_errors(client):
    bad_var = {**MIN_CFG, "variables": []}
    assert client.post("/api/agents", json={"name": "x1", "config": bad_var}).status_code == 422
    bad_tool = {**MIN_CFG, "tools": ["launch_rockets"]}
    assert client.post("/api/agents", json={"name": "x2", "config": bad_tool}).status_code == 422
    bad_q = {**MIN_CFG, "dispositions": [{"id": "Outcome", "type": "enum", "question": "?", "choices": ["a"]}]}
    assert client.post("/api/agents", json={"name": "x3", "config": bad_q}).status_code == 422


def test_runtime_requires_worker_token(client):
    aid = client.get("/api/agents").json()[0]["id"]
    assert client.get(f"/api/internal/agents/{aid}/runtime").status_code == 401


def test_test_session_token_dispatches_worker_with_metadata(client):
    aid = client.get("/api/agents").json()[0]["id"]
    out = client.post(f"/api/agents/{aid}/test-session", json={"context": {"customer_name": "Shivam"}}).json()
    claims = api.TokenVerifier("devkey", "devsecret-devsecret-devsecret-devsecret").verify(out["token"])
    dispatch = claims.room_config.agents[0]
    meta = json.loads(dispatch.metadata)
    assert dispatch.agent_name == "yaprr-agent"
    assert meta["agent_id"] == aid and meta["version"] == 1
    assert meta["context"]["customer_name"] == "Shivam" and meta["context"]["scenario"] == "due_today"


def test_duplicate_and_legacy_fallback_migration(client):
    aid = client.get("/api/agents").json()[0]["id"]
    dup = client.post(f"/api/agents/{aid}/duplicate").json()
    assert dup["status"] == "draft" and dup["name"].endswith("(copy)") and dup["published_version"] is None
    legacy = {**MIN_CFG, "llm": {"provider": "groq", "model": "qwen/qwen3.8-27b", "fallback_model": "gemini-3.5-flash"}}
    a = client.post("/api/agents", json={"name": "legacy", "config": legacy}).json()
    assert a["config"]["llm"]["fallbacks"] == [{"provider": "google", "model": "gemini-3.5-flash", "reasoning_effort": ""}]


def test_admin_token_protects_dashboard_but_not_worker_or_health(client, monkeypatch):
    from yaprr_api.settings import get_settings
    monkeypatch.setattr(get_settings(), "admin_token", "s3cret")
    assert client.get("/api/agents").status_code == 401
    assert client.get("/api/agents", headers={"Authorization": "Bearer nope"}).status_code == 401
    ok = client.get("/api/agents", headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200
    aid = ok.json()[0]["id"]
    assert client.get(f"/api/internal/agents/{aid}/runtime", headers=W).status_code == 200  # worker token only
    assert client.get("/api/health").status_code == 200
