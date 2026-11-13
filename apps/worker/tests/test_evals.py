"""Evals harness: scoring rules, plus one full simulated call through the real agent,
tools and read-back gate, with scripted LLMs instead of real ones (no keys, no cost)."""

import asyncio
import dataclasses
import json
import os

from livekit.agents import APIConnectOptions, llm as lk_llm

from evals import scoring

PERSONA = {"id": "promise_date", "caller": "x",
           "checks": {"must_call": {"log_payment_promise": {"amount": 4200}}, "must_not_call": ["transfer_to_human"]},
           "facts": {"promised_date": "28 November", "amount": 4200}}


class ScriptedLLM(lk_llm.LLM):
    """Each chat() returns the next scripted item: a string, or ("tool", name, args)."""

    def __init__(self, script):
        super().__init__()
        self.script = list(script)

    def chat(self, *, chat_ctx, tools=None, conn_options=APIConnectOptions(), **_):
        return _Stream(self, self.script.pop(0), chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)


class _Stream(lk_llm.LLMStream):
    def __init__(self, llm, step, **kw):
        super().__init__(llm, **kw)
        self.step = step

    async def _run(self):
        if isinstance(self.step, tuple):
            _, name, args = self.step
            call = lk_llm.FunctionToolCall(name=name, arguments=json.dumps(args), call_id=f"c{id(self)}")
            delta = lk_llm.ChoiceDelta(role="assistant", tool_calls=[call])
        else:
            delta = lk_llm.ChoiceDelta(role="assistant", content=self.step)
        self._event_ch.send_nowait(lk_llm.ChatChunk(id="x", delta=delta))


def test_scoring_rules():
    promise = {"promised_date": "28 November", "amount": 4200}
    turns = [{"role": "agent", "text": "namaste"}, {"role": "caller", "text": "28 ko"},
             {"role": "tool", "name": "log_payment_promise", "args": promise, "output": "NOT done yet. read back"},
             {"role": "agent", "text": "अट्ठाईस नवंबर, चार हज़ार दो सौ, सही है?"}, {"role": "caller", "text": "haan"},
             {"role": "tool", "name": "log_payment_promise", "args": promise, "output": "Promise logged."}]
    checks = scoring.check(PERSONA, turns)
    assert all(checks.values()), checks
    assert scoring.key_facts_correct(PERSONA, turns) is True
    # skipping the read-back, or logging the wrong day, fails
    no_rb = [t for t in turns if not str(t.get("output", "")).startswith("NOT")]
    assert scoring.check(PERSONA, no_rb)["read back before acting"] is False
    wrong = [dict(t, args={**t["args"], "promised_date": "2026-11-20"}) if t["role"] == "tool" else t for t in turns]
    assert scoring.key_facts_correct(PERSONA, wrong) is False
    assert scoring.check(PERSONA, turns + [{"role": "agent", "text": "main ek AI hoon"}])["never claimed to be an AI"] is False


def test_day_of_reads_llm_dates():
    assert scoring.day_of("28 November") == 28 and scoring.day_of("2026-11-21") == 21
    assert scoring.day_of("अट्ठाईस नवंबर") == 28 and scoring.day_of("26th Nov") == 26 and scoring.day_of("kal") is None


def test_full_simulated_call_goes_through_the_real_agent_and_gate(monkeypatch):
    for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "DEEPGRAM_API_KEY", "CARTESIA_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.setenv(k, "x")
    from evals import run
    from services.config import load_app_config
    from services.runtime import LOCAL_DEMO

    demo = json.loads(LOCAL_DEMO.read_text(encoding="utf-8"))
    promise = {"promised_date": "28 November", "amount": 4200}
    agent_llm = ScriptedLLM(["जी, आपकी EMI आज due है। कब तक कर पाएँगे?",
                             ("tool", "log_payment_promise", promise), "अट्ठाईस नवंबर, चार हज़ार दो सौ। सही है?",
                             ("tool", "log_payment_promise", promise), "धन्यवाद, नोट कर लिया।"])
    caller_llm = ScriptedLLM(["haan main Ramesh", "28 November ko dunga", "haan sahi hai", run.END])
    monkeypatch.setattr(run, "build_llm", lambda _cfg: agent_llm)
    config = dataclasses.replace(load_app_config())

    sim = asyncio.run(run.simulate(PERSONA, demo["config"], demo["context"], config, caller_llm))
    assert sim["error"] is None, sim["error"]
    tools = [t for t in sim["turns"] if t["role"] == "tool"]
    assert [t["output"][:12] for t in tools] == ["NOT done yet", "Promise logg"]  # the gate made it read back
    assert all(scoring.check(PERSONA, sim["turns"]).values())
    assert scoring.key_facts_correct(PERSONA, sim["turns"]) is True


def test_wer_counts_subs_deletes_inserts():
    from evals.wer import edit_counts, normalize, wer
    assert wer("kal paanch hazaar de dunga", "kal paanch hazaar dunga") == 0.2
    assert edit_counts(normalize("a b c"), normalize("a x c d")) == (1, 0, 1)
    assert wer("मैं कल पाँच हज़ार दे दूँगा।", "मैं कल पाँच हजार दे दूँगा") == 0  # nukta + danda don't count
