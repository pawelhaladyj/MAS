import json
from agents.protocol import acl_handler
from agents.protocol.acl_messages import AclMessage
import agents.protocol.handler as handler_mod  # do monkeypatcha

class DummyMsg:
    def __init__(self, body, sender="peer@xmpp", meta=None):
        self.body = body
        self.sender = sender
        self.metadata = meta or {}

class DummyAgent:
    def __init__(self):
        self.outbox = []
        self.called = False

    async def send(self, msg):
        self.outbox.append(msg)

def test_acl_handler_logs_in(asyncio_event_loop, monkeypatch):
    calls = []
    def fake_log_acl_event(cid, direction, acl_dict):
        calls.append((cid, direction, acl_dict))

    monkeypatch.setattr(handler_mod, "log_acl_event", fake_log_acl_event, raising=False)

    agent = DummyAgent()

    @acl_handler
    async def on_msg(self, acl: AclMessage, raw_msg):
        self.called = True

    acl = AclMessage.build_inform_fact("conv-in", "budget_total", 111)
    raw = DummyMsg(acl.to_json(), meta={"conversation_id": "conv-in"})

    asyncio_event_loop.run_until_complete(on_msg(agent, raw))

    assert agent.called is True
    assert calls, "telemetry should be called"
    assert calls[0][0] == "conv-in" and calls[0][1] == "IN"
    assert calls[0][2]["payload"]["type"] == "FACT"
