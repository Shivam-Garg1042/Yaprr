from agents.configured_agent import ConfiguredAgent, render
from services.runtime import LOCAL_DEMO
import json


def test_render_keeps_unknown_variables():
    assert render("Hi {customer_name}, due {due_date}", {"customer_name": "Ramesh"}) == "Hi Ramesh, due {due_date}"


def test_agent_built_from_config_with_only_enabled_tools():
    cfg = json.loads(LOCAL_DEMO.read_text(encoding="utf-8"))["config"]
    cfg = {**cfg, "tools": ["hangup", "log_payment_promise"]}
    events = []
    a = ConfiguredAgent(cfg, {"customer_name": "Ramesh", "scenario": "overdue"}, emit=lambda t, p: events.append(t))
    assert "Ramesh" in a.opening_line and "Voice rules" in a.instructions and "Scenario: overdue" in a.instructions
    names = sorted(t.info.name if hasattr(t, "info") else t.__name__ for t in a.tools)
    assert names == ["hangup", "log_payment_promise"]
