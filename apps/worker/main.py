"""
yaprr voice worker.

    python main.py download-files   # one-time: turn-detector model
    python main.py dev              # serve calls dispatched by the API ("Talk to agent", campaigns)
    python main.py console          # talk in the terminal (uses DEFAULT_AGENT_ID or the local demo agent)

Per call: resolve which agent (and version) to run from the job metadata, build
the STT -> LLM -> TTS pipeline with that agent's settings, run the call with
metrics + safety guards, then write one call record (latency, cost, transcript,
dispositions) to runtime/calls/ and POST it to the API.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from livekit.agents import JobContext, JobProcess, WorkerOptions, cli

from agents.configured_agent import ConfiguredAgent
from services.call_metrics import CallMetrics
from services.config import load_app_config
from services.dispositions import extract_dispositions, transcript_from_history
from services.events import EventLogger
from services.pii import mask_value
from services.pipeline import build_room_options, build_session, load_vad
from services.pricing import pricing_for
from services.runtime import apply_agent_overrides, post_call_record, resolve_agent
from services.safety import CallGuard

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
logger = logging.getLogger(__name__)

# Always keep a UTF-8 log file (piping Windows console output breaks on emoji / Hindi).
Path("runtime").mkdir(exist_ok=True)
_file_handler = logging.FileHandler("runtime/worker.log", encoding="utf-8")
_file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s"))
_file_handler.setLevel(logging.INFO)
for _name in ("", "livekit", "livekit.agents"):
    logging.getLogger(_name).addHandler(_file_handler)


def prewarm(proc: JobProcess) -> None:
    """Once per worker process: validate env + load the Silero VAD."""
    config = load_app_config()
    proc.userdata["config"] = config
    proc.userdata["event_logger"] = EventLogger(config.events_log_path)
    proc.userdata["vad"] = load_vad(config.turn)
    logger.info("[yaprr] Prewarm complete. API: %s", os.getenv("YAPRR_API_URL") or "(none: local demo agent)")


async def entrypoint(ctx: JobContext) -> None:
    base_config = ctx.proc.userdata["config"]
    event_logger: EventLogger = ctx.proc.userdata["event_logger"]
    vad = ctx.proc.userdata["vad"]
    call_id = uuid.uuid4().hex

    resolved = await resolve_agent(ctx.job.metadata)
    config = apply_agent_overrides(base_config, resolved.config)
    config = dataclasses.replace(config, pricing=pricing_for(config))
    log = lambda t, p: event_logger.write(t, {"call_id": call_id, "room_name": ctx.room.name, **p})  # noqa: E731

    logger.info("[yaprr] New call %s | room=%s | agent=%s v%s (%s) | llm=%s:%s",
                call_id, ctx.room.name, resolved.name, resolved.version, resolved.source,
                config.llm_provider, config.llm_model)
    log("call_received", {"agent_id": resolved.agent_id, "version": resolved.version, "context": resolved.context})

    await ctx.connect()
    # The room name is stable for the whole call, so tool idempotency keys survive a worker reconnect.
    agent = ConfiguredAgent(resolved.config, resolved.context, emit=log, call_key=ctx.room.name)
    session = build_session(config, vad)

    # ── observability ─────────────────────────────────────────────────────────
    call_metrics = CallMetrics(pricing=config.pricing)
    tool_calls: list[dict] = []
    close_info: dict = {}
    started_at = time.time()

    @session.on("metrics_collected")
    def _on_metrics(ev) -> None:
        call_metrics.on_metrics(ev.metrics)

    @session.on("function_tools_executed")
    def _on_tools(ev) -> None:
        for call in ev.function_calls:
            tool_calls.append({"name": call.name, "arguments": call.arguments, "at": round(time.time() - started_at, 2)})

    @session.on("close")
    def _on_close(ev) -> None:
        close_info["reason"] = getattr(ev.reason, "value", str(ev.reason))
        close_info["error"] = str(ev.error) if ev.error else None
        # Closing the session (hangup tool / CallGuard) doesn't end the job by itself.
        ctx.shutdown(reason=close_info["reason"])

    if hasattr(session.llm, "on"):  # FallbackAdapter: count failovers
        @session.llm.on("llm_availability_changed")
        def _on_llm_availability(ev) -> None:
            if not ev.available:
                call_metrics.usage.llm_failovers += 1
            log("llm_availability_changed", {"llm": getattr(ev.llm, "model", str(ev.llm)), "available": ev.available})

    guard = CallGuard(session, config.safety, on_event=log)

    async def finalize(_reason: str = "") -> None:
        """Once, at job shutdown: persist the record first, then dispositions, then update."""
        guard.stop()
        ended_at = time.time()
        duration = ended_at - started_at
        # Everything we keep is masked (phone, PAN, Aadhaar, account numbers...). The live call wasn't.
        pii_found: Counter = Counter()
        transcript = mask_value(transcript_from_history(session.history), pii_found)
        record = {
            "id": call_id,
            "agent_id": resolved.agent_id,
            "agent_version": resolved.version,
            "room_name": ctx.room.name,
            "started_at": datetime.fromtimestamp(started_at, timezone.utc).isoformat(),
            "ended_at": datetime.fromtimestamp(ended_at, timezone.utc).isoformat(),
            "duration_s": round(duration, 1),
            "ended_by": guard.end_reason or close_info.get("reason") or _reason or "unknown",
            "context": mask_value(resolved.context, pii_found),
            "pipeline": {
                "agent_name": resolved.name, "agent_source": resolved.source, "close_error": close_info.get("error"),
                "stt": f"{config.stt_model}/{config.stt_language}", "llm": f"{config.llm_provider}:{config.llm_model}",
                "llm_fallbacks": [f"{f.provider}:{f.model}" for f in config.llm_fallbacks], "tts": f"{config.tts_model}@{config.tts_speed}",
                "turn": config.turn.__dict__, "safety": config.safety.__dict__,
            },
            "metrics": call_metrics.summary(duration),
            "tool_calls": mask_value(tool_calls, pii_found),
            "dispositions": {"answers": None, "status": "pending"},
            "transcript": transcript,
        }
        record["metrics"]["pii_masked"] = dict(pii_found)
        out_dir = Path(config.call_records_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{datetime.now():%Y%m%d-%H%M%S}_{ctx.room.name}.json"

        def save() -> None:
            out_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

        save()  # never lose the call, even if analysis below is killed
        await post_call_record(record)

        dispositions: dict = {"answers": None, "status": "disabled"}
        if config.dispositions_enabled:
            try:
                dispositions = await extract_dispositions(
                    transcript, resolved.config.get("use_case", "collections"),
                    api_key=config.google_api_key, model=config.disposition_model,
                    tool_calls=record["tool_calls"], questions=resolved.config.get("dispositions") or None,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("[yaprr] Disposition extraction failed")
                dispositions = {"answers": None, "error": str(exc)}
        record["dispositions"] = mask_value(dispositions)
        save()
        synced = await post_call_record(record)

        lat = record["metrics"]["latency"]["response"]
        outcome = (dispositions.get("answers") or {}).get("call_outcome")
        logger.info("[yaprr] Call done %s | %.0fs | p50=%sms p95=%sms | ₹%s | outcome=%s | api=%s",
                    call_id, duration, lat["p50_ms"], lat["p95_ms"], record["metrics"]["cost"]["inr_total"],
                    outcome, synced)
        log("call_completed", {"record_path": str(out_path), "synced_to_api": synced, "outcome": outcome})

    ctx.add_shutdown_callback(finalize)
    log("session_starting", {})
    await session.start(room=ctx.room, agent=agent, room_options=build_room_options(config))
    guard.start()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(
        entrypoint_fnc=entrypoint,
        prewarm_fnc=prewarm,
        # Explicit dispatch: the API's test sessions / campaigns dispatch this name.
        # Set WORKER_AGENT_NAME= (empty) to get automatic dispatch to every room instead.
        agent_name=os.getenv("WORKER_AGENT_NAME", "yaprr-agent"),
        # Post-call work (dispositions with retries) needs more than the 10 s default.
        shutdown_process_timeout=45,
    ))
