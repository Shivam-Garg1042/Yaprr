"""Post-call dispositions: turn a transcript into structured answers.

After every call, one LLM request reads the transcript and answers a fixed set
of questions per agent type (did we reach the right person? outcome? promise
date? main objection?). This is what dashboards, retries and CRM updates run on.

Design choices:
  - Questions are data (QUESTIONS below), not code, so ops can change them.
  - JSON-schema constrained output + server-side validation: an answer outside
    the allowed choices becomes "unknown" instead of polluting reports.
  - No-conversation calls (nobody spoke) skip the LLM entirely -> zero cost.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from services.gemini import thinking_config_for

logger = logging.getLogger(__name__)

UNKNOWN = "unknown"

QUESTIONS: dict[str, list[dict[str, Any]]] = {
    "collections": [
        {"id": "right_party_contact", "type": "enum",
         "question": "Did the agent speak with the intended customer?",
         "choices": ["yes", "family_member", "wrong_number", "unclear"]},
        {"id": "call_outcome", "type": "enum",
         "question": "What was the final outcome of the conversation?",
         "choices": ["promise_to_pay", "already_paid", "callback_requested", "refused",
                     "dispute", "escalated", "undecided"]},
        {"id": "ptp_timing", "type": "enum",
         "question": "If the driver promised to pay, when?",
         "choices": ["today", "tomorrow", "within_3_days", "within_7_days", "later", "not_applicable"]},
        {"id": "ptp_date", "type": "text",
         "question": "Exact promised payment date as spoken (e.g. '28 October'), or empty."},
        {"id": "primary_objection", "type": "enum",
         "question": "Main reason given for not paying or delaying.",
         "choices": ["no_money", "low_earnings", "battery_issue", "vehicle_issue", "health_or_family",
                     "already_paid", "disputes_amount", "none"]},
        {"id": "payment_link_sent", "type": "bool",
         "question": "Did the agent send or offer a payment link / app details?"},
        {"id": "consequences_mentioned", "type": "bool",
         "question": "Did the agent mention penalty or CIBIL impact?"},
        {"id": "technical_complaint", "type": "bool",
         "question": "Did the driver report a battery or technical problem?"},
        {"id": "risk_level", "type": "enum",
         "question": "Risk that this account will not pay, based on the call.",
         "choices": ["low", "medium", "high"]},
        {"id": "summary", "type": "text",
         "question": "2-3 sentence summary in English with any dates or amounts mentioned."},
    ],
    "sales": [
        {"id": "call_outcome", "type": "enum",
         "question": "What was the outcome?",
         "choices": ["interested", "visit_booked", "callback_requested", "not_interested",
                     "wrong_number", "undecided"]},
        {"id": "vehicle_type", "type": "enum",
         "question": "What vehicle does the lead use?",
         "choices": ["e_rickshaw", "e_loader", "other", "unknown"]},
        {"id": "current_battery", "type": "enum",
         "question": "What battery do they use today?",
         "choices": ["lead_acid", "lithium", "none", "unknown"]},
        {"id": "budget_discussed", "type": "bool", "question": "Was price or EMI discussed?"},
        {"id": "primary_objection", "type": "enum",
         "question": "Main objection raised.",
         "choices": ["price", "trust", "already_has_battery", "needs_family_approval", "none"]},
        {"id": "follow_up_date", "type": "text",
         "question": "Any follow-up date/time agreed, as spoken, or empty."},
        {"id": "summary", "type": "text",
         "question": "2-3 sentence summary in English."},
    ],
}


def transcript_from_history(history: Any) -> list[dict[str, str]]:
    """Flatten a LiveKit ChatContext into [{role, text}] (user/assistant only)."""
    turns: list[dict[str, str]] = []
    for item in getattr(history, "items", []):
        if getattr(item, "type", None) != "message" or item.role not in ("user", "assistant"):
            continue
        text = (item.text_content or "").strip()
        if text:
            turns.append({"role": "customer" if item.role == "user" else "agent", "text": text,
                          "interrupted": bool(getattr(item, "interrupted", False))})
    return turns


def build_schema(questions: list[dict[str, Any]]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for q in questions:
        if q["type"] == "enum":
            props[q["id"]] = {"type": "STRING", "enum": q["choices"], "description": q["question"]}
        elif q["type"] == "bool":
            props[q["id"]] = {"type": "BOOLEAN", "description": q["question"]}
        else:
            props[q["id"]] = {"type": "STRING", "description": q["question"]}
    return {"type": "OBJECT", "properties": props, "required": [q["id"] for q in questions]}


def build_prompt(transcript: list[dict[str, str]], questions: list[dict[str, Any]],
                 tool_calls: list[dict[str, Any]] | None = None) -> str:
    lines = "\n".join(f"{t['role'].upper()}: {t['text']}" for t in transcript)
    tools = ", ".join(f"{c['name']}({c.get('arguments', '')})" for c in (tool_calls or [])) or "none"
    qs = "\n".join(f"- {q['id']}: {q['question']}" + (f" Choices: {q['choices']}" if q.get("choices") else "")
                   for q in questions)
    return (
        "You review a recorded phone call between a voice agent and a customer "
        "(Hinglish). Answer each question using ONLY what is in the transcript. "
        "If the transcript does not show it, pick the most neutral choice.\n\n"
        "Actions (sending a link, logging a promise) only count if they appear in TOOLS CALLED; "
        "the agent saying it did something is not enough.\n\n"
        f"QUESTIONS:\n{qs}\n\nTOOLS CALLED: {tools}\n\nTRANSCRIPT:\n{lines}"
    )


def validate_answers(raw: dict[str, Any], questions: list[dict[str, Any]]) -> dict[str, Any]:
    """Coerce model output to the schema. Bad/missing values become UNKNOWN / None."""
    clean: dict[str, Any] = {}
    for q in questions:
        v = raw.get(q["id"])
        if q["type"] == "enum":
            clean[q["id"]] = v if v in q["choices"] else UNKNOWN
        elif q["type"] == "bool":
            if isinstance(v, str):
                v = {"true": True, "yes": True, "false": False, "no": False}.get(v.strip().lower())
            clean[q["id"]] = v if isinstance(v, bool) else None
        else:
            clean[q["id"]] = str(v).strip() if v not in (None, "") else ""
    return clean


NO_CONVERSATION = "no_conversation"  # set by code only, never offered to the LLM


def no_conversation_answers(questions: list[dict[str, Any]]) -> dict[str, Any]:
    answers = validate_answers({"summary": "No conversation: the customer did not speak."}, questions)
    answers["call_outcome"] = NO_CONVERSATION
    return answers


async def extract_dispositions(
    transcript: list[dict[str, str]],
    agent_type: str,
    *,
    api_key: str,
    model: str,
    fallback_models: tuple[str, ...] = ("gemini-3.5-flash-lite",),
    tool_calls: list[dict[str, Any]] | None = None,
    questions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """`questions` come from the agent's config (UI-editable); QUESTIONS is the fallback."""
    questions = questions or QUESTIONS.get(agent_type, QUESTIONS["collections"])
    if not any(t["role"] == "customer" for t in transcript):
        return {"answers": no_conversation_answers(questions), "skipped_llm": True}

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    started = time.perf_counter()
    resp, last_err, attempts = None, None, 0
    # Post-call, nobody is waiting: retry 503/"high demand" with backoff, then try fallbacks.
    for m in [model, *fallback_models]:
        for delay in (0, 2, 5):
            attempts += 1
            if delay:
                await asyncio.sleep(delay)
            try:
                resp = await client.aio.models.generate_content(
                    model=m,
                    contents=build_prompt(transcript, questions, tool_calls),
                    config=types.GenerateContentConfig(
                        temperature=0,
                        response_mime_type="application/json",
                        response_schema=build_schema(questions),
                        thinking_config=types.ThinkingConfig(**thinking_config_for(m)),
                    ),
                )
                model = m
                break
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                logger.warning("[yaprr] Disposition attempt %s on %s failed: %s", attempts, m, str(exc)[:120])
        if resp is not None:
            break
    if resp is None:
        raise RuntimeError(f"all disposition attempts failed: {last_err}")
    latency_ms = round((time.perf_counter() - started) * 1000)
    try:
        raw = json.loads(resp.text or "{}")
    except json.JSONDecodeError:
        logger.warning("[yaprr] Disposition JSON parse failed; storing unknowns")
        raw = {}
    usage = getattr(resp, "usage_metadata", None)
    return {
        "answers": validate_answers(raw, questions),
        "skipped_llm": False,
        "model": model,
        "latency_ms": latency_ms,
        "attempts": attempts,
        "input_tokens": getattr(usage, "prompt_token_count", None),
        "output_tokens": getattr(usage, "candidates_token_count", None),
    }
