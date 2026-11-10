import asyncio
from types import SimpleNamespace

from services.config import SafetySettings
from services.safety import CallGuard


class FakeHandle:
    async def wait_for_playout(self):
        return None


class FakeSession:
    def __init__(self):
        self.handlers, self.said, self.closed = {}, [], False

    def on(self, name, fn):
        self.handlers[name] = fn

    def say(self, text, **_):
        self.said.append(text)
        return FakeHandle()

    async def aclose(self):
        self.closed = True


def test_inactivity_nudges_then_hangs_up_and_resets_on_speech():
    async def run():
        s, events = FakeSession(), []
        g = CallGuard(s, SafetySettings(max_call_seconds=0, max_inactivity_prompts=2), lambda t, p: events.append(t))
        g.start()
        away = SimpleNamespace(new_state="away")
        s.handlers["user_state_changed"](away)
        s.handlers["user_state_changed"](SimpleNamespace(new_state="speaking"))  # resets counter
        s.handlers["user_state_changed"](away)
        s.handlers["user_state_changed"](away)
        assert not s.closed and g.inactivity_prompts == 2
        s.handlers["user_state_changed"](away)  # 3rd silence after 2 nudges -> end
        await asyncio.sleep(0.01)
        assert s.closed and g.end_reason == "inactivity"
        assert events.count("inactivity_prompt") == 3 and "call_guard_end" in events
    asyncio.run(run())


def test_max_duration_ends_call():
    async def run():
        s = FakeSession()
        g = CallGuard(s, SafetySettings(max_call_seconds=0), lambda *_: None)
        g.settings = SafetySettings(max_call_seconds=1)
        g.start()
        await asyncio.sleep(1.1)
        assert s.closed and g.end_reason == "max_duration"
        assert s.said[-1] == g.settings.closing_message
    asyncio.run(run())
