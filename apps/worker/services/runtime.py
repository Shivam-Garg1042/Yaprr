"""Which agent runs this call, and with what settings.

Resolution order for a call:
  1. Job metadata from the dispatch (set by the API's test-session / campaign
     dispatcher): {"agent_id", "version", "draft", "context"}
  2. DEFAULT_AGENT_ID env -> fetched from the API (handy for `console` mode)
  3. local_agents/demo_collections.json (works with no API at all)

The agent's config (prompt, voice, LLM, turn, safety, dispositions) comes from
the database; secrets and infra defaults stay in the worker's env. An agent
overrides env defaults only for the fields it sets.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiohttp

from services.config import AppConfig, LLMSpec

logger = logging.getLogger(__name__)

LOCAL_DEMO = Path(__file__).resolve().parents[1] / "local_agents" / "demo_collections.json"


@dataclass
class ResolvedAgent:
    agent_id: str | None
    name: str
    version: int | None
    config: dict[str, Any]
    context: dict[str, str] = field(default_factory=dict)
    source: str = "local"  # api | local


def parse_job_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        logger.warning("[yaprr] job metadata is not JSON; ignoring")
        return {}


async def fetch_runtime(api_url: str, token: str, agent_id: str, version: int | None, draft: bool) -> dict[str, Any]:
    params: dict[str, str] = {"draft": "true"} if draft else ({"version": str(version)} if version else {})
    url = f"{api_url.rstrip('/')}/api/internal/agents/{agent_id}/runtime"
    timeout = aiohttp.ClientTimeout(total=5)
    async with aiohttp.ClientSession(timeout=timeout) as http:
        async with http.get(url, params=params, headers={"X-Worker-Token": token}) as resp:
            resp.raise_for_status()
            return await resp.json()


async def resolve_agent(job_metadata: str | None) -> ResolvedAgent:
    meta = parse_job_metadata(job_metadata)
    api_url = os.getenv("YAPRR_API_URL", "")
    token = os.getenv("YAPRR_WORKER_TOKEN", "dev-worker-token")
    agent_id = meta.get("agent_id") or os.getenv("DEFAULT_AGENT_ID") or None
    context = {str(k): str(v) for k, v in (meta.get("context") or {}).items()}

    if agent_id and api_url:
        try:
            rt = await fetch_runtime(api_url, token, agent_id, meta.get("version"), bool(meta.get("draft")))
            return ResolvedAgent(agent_id=rt["agent_id"], name=rt["name"], version=rt["version"] or None,
                                 config=rt["config"], context=context, source="api")
        except Exception as exc:  # noqa: BLE001 - a call must still happen
            logger.error("[yaprr] could not load agent %s from API (%s); using local demo agent", agent_id, exc)

    demo = json.loads(LOCAL_DEMO.read_text(encoding="utf-8"))
    return ResolvedAgent(agent_id=None, name=demo["name"], version=None, config=demo["config"],
                         context={**demo.get("context", {}), **context}, source="local")


def _fallbacks_from(llm: dict[str, Any], base: AppConfig) -> tuple[LLMSpec, ...]:
    if "fallbacks" in llm:
        return tuple(LLMSpec(f["provider"], f["model"], f.get("reasoning_effort", "")) for f in llm["fallbacks"])
    if "fallback_model" in llm:  # configs saved before multi-provider fallbacks
        return (LLMSpec("google", llm["fallback_model"]),) if llm["fallback_model"] else ()
    return base.llm_fallbacks


def apply_agent_overrides(base: AppConfig, cfg: dict[str, Any]) -> AppConfig:
    """Return a copy of the env config with the agent's choices applied."""
    llm, voice, stt = cfg.get("llm", {}), cfg.get("voice", {}), cfg.get("stt", {})
    turn = {k: v for k, v in (cfg.get("turn") or {}).items() if v is not None}
    safety = cfg.get("safety") or {}

    new_turn = dataclasses.replace(base.turn, **{k: v for k, v in turn.items() if hasattr(base.turn, k)})
    new_safety = dataclasses.replace(base.safety, **{k: v for k, v in safety.items() if hasattr(base.safety, k)})
    changes: dict[str, Any] = {"turn": new_turn, "safety": new_safety}
    if llm:
        changes |= {
            "llm_provider": llm.get("provider", base.llm_provider),
            "llm_model": llm.get("model", base.llm_model),
            "llm_temperature": llm.get("temperature", base.llm_temperature),
            "llm_reasoning_effort": llm.get("reasoning_effort", base.llm_reasoning_effort),
            "llm_fallbacks": _fallbacks_from(llm, base),
        }
        if llm.get("provider") != base.llm_provider:
            changes |= {"llm_base_url": "", "llm_api_key": ""}  # env URL/key belonged to the old provider
    if voice:
        changes |= {"tts_voice": voice.get("voice_id", base.tts_voice), "tts_speed": voice.get("speed", base.tts_speed),
                    "tts_language": voice.get("language", base.tts_language)}
    if stt:
        changes |= {"stt_model": stt.get("model", base.stt_model), "stt_language": stt.get("language", base.stt_language)}
    return dataclasses.replace(base, **changes)


async def post_call_record(record: dict[str, Any]) -> bool:
    """Send the call record to the API. Never raises; the local JSON file is the backup."""
    api_url = os.getenv("YAPRR_API_URL", "")
    if not api_url:
        return False
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as http:
            async with http.post(f"{api_url.rstrip('/')}/api/internal/calls", json=record,
                                 headers={"X-Worker-Token": os.getenv("YAPRR_WORKER_TOKEN", "dev-worker-token")}) as r:
                r.raise_for_status()
                return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("[yaprr] could not post call record to API: %s", exc)
        return False
