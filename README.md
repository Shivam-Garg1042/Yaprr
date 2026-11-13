# yaprr

**Outbound voice agents for Hindi/Hinglish calls (EMI reminders, sales), built and measured end to end.**

Create an agent in the browser (script, voice, LLM, tools, post-call questions), publish a version,
talk to it, and see every call's latency per stage, cost per minute and extracted outcome.

```
apps/web     React + Vite UI: agents, script editor, talk-to-agent, calls, dashboard
apps/api     FastAPI + Postgres: agents, immutable versions, call records, stats
apps/worker  LiveKit Agents worker: Deepgram STT → LLM (Groq/Gemini, with failover) → Cartesia TTS
```

```
 Browser ──► API ── mint LiveKit token, dispatch "yaprr-agent" with {agent_id, version, context}
                │
 LiveKit room ◄─┘──► Worker: load agent config from API ─► run call (metrics + safety guards)
                                   │
                                   └─► POST call record (latency, cost, transcript, dispositions) ─► API ─► Postgres
```

## What's measured on every call
- **Latency per turn**: end-of-utterance, LLM first token, TTS first audio, total response (p50/p95).
- **Cost per call and per minute**: from real usage (STT seconds, LLM tokens, TTS characters) × unit prices.
- **Interrupted replies**: a proxy for "the agent talks too much".
- **Dispositions**: an LLM answers the agent's own questions from the transcript *and the tools that actually ran*.

## Run it locally (Windows PowerShell)

```powershell
# 0. Postgres (or skip Docker and set DATABASE_URL=sqlite:///./yaprr.db in apps/api/.env)
docker compose up -d

# 1. API
cd apps/api; python -m venv venv; venv\Scripts\activate
pip install -r requirements-dev.txt; copy .env.example .env   # fill LIVEKIT_*, WORKER_TOKEN
uvicorn yaprr_api.main:app --reload --port 8000

# 2. Worker (new terminal)
cd apps/worker; python -m venv venv; venv\Scripts\activate
pip install -r requirements-dev.txt; copy .env.example .env   # provider keys, same WORKER_TOKEN
python main.py download-files
$env:PYTHONUTF8=1; python main.py dev

# 3. Web (new terminal)
cd apps/web; npm install; npm run dev     # http://localhost:5173
```

Open an agent → **Talk to agent** → Start test call. The call shows up under **Calls** when you hang up.

Deploy: see [docs/DEPLOY.md](docs/DEPLOY.md) (Vercel + AWS Lambda + Neon + LiveKit Cloud).

Tests: `pytest -q` in `apps/api` (also runs against Postgres via `DATABASE_URL`) and in `apps/worker`.

## Roadmap
- [x] **M1** Agents from the database: editor, versions, test calls, call records into the API
- [x] **M2a** Dashboards: global + per-agent, filters (agent, version, outcome, time), versions compared, failover rate
- [ ] **M2b** Alerts on p95 latency / cost / failover rate; noise + voice experiments (docs/QUALITY_PLAN.md)
- [ ] **M3** Evals: simulated callers × scenarios, scored per agent version
- [ ] **M4** Campaigns + real phone calls (SIP), retries, calling hours
- [x] **M5a** Deploy-ready: Alembic migrations, access token, Dockerfiles, deploy guide
- [ ] **M5b** Live deploy + case study

Demo agents use a fictional company ("Voltly").
