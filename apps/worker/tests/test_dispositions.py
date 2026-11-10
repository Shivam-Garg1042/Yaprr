import asyncio
from types import SimpleNamespace

from services.dispositions import (QUESTIONS, UNKNOWN, build_schema, extract_dispositions,
                                   transcript_from_history, validate_answers)

Q = QUESTIONS["collections"]


def test_validate_coerces_bad_values():
    out = validate_answers({"call_outcome": "made_up", "payment_link_sent": "yes",
                            "technical_complaint": "maybe", "summary": None}, Q)
    assert out["call_outcome"] == UNKNOWN
    assert out["payment_link_sent"] is True
    assert out["technical_complaint"] is None
    assert out["summary"] == ""
    assert set(out) == {q["id"] for q in Q}


def test_schema_has_every_question_required():
    s = build_schema(Q)
    assert s["required"] == [q["id"] for q in Q]
    assert s["properties"]["call_outcome"]["enum"] == Q[1]["choices"]


def test_transcript_from_history_keeps_only_spoken_turns():
    msg = lambda role, text: SimpleNamespace(type="message", role=role, text_content=text, interrupted=False)
    hist = SimpleNamespace(items=[msg("system", "rules"), msg("assistant", "Namaste"),
                                  SimpleNamespace(type="function_call"), msg("user", "haan"), msg("user", " ")])
    assert transcript_from_history(hist) == [
        {"role": "agent", "text": "Namaste", "interrupted": False},
        {"role": "customer", "text": "haan", "interrupted": False},
    ]


def test_no_conversation_skips_llm():
    res = asyncio.run(extract_dispositions([{"role": "agent", "text": "hello?"}], "collections",
                                           api_key="unused", model="unused"))
    assert res["skipped_llm"] is True
    assert res["answers"]["call_outcome"] == "no_conversation"


def test_no_conversation_is_never_offered_to_llm():
    assert "no_conversation" not in build_schema(Q)["properties"]["call_outcome"]["enum"]
    # and if the model returns it anyway, it is rejected
    assert validate_answers({"call_outcome": "no_conversation"}, Q)["call_outcome"] == UNKNOWN


def test_prompt_lists_tool_calls_so_claims_need_evidence():
    from services.dispositions import build_prompt
    p = build_prompt([{"role": "agent", "text": "link bhej diya"}], Q, [{"name": "create_payment_request", "arguments": '{"amount": 1500}'}])
    assert "TOOLS CALLED: create_payment_request" in p
    assert "TOOLS CALLED: none" in build_prompt([{"role": "agent", "text": "hi"}], Q)
