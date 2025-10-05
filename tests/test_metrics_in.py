import agents.protocol.handler as handler_mod
from agents.protocol import acl_handler
from agents.protocol.acl_messages import AclMessage

class DummyMsg:
    def __init__(self, body, sender="peer@xmpp", meta=None):
        self.body = body
        self.sender = sender
        self.metadata = meta or {}

class DummyAgent:
    def __init__(self):
        self.called = False
    async def send(self, msg):  # nie używamy tu
        pass

def test_metrics_increment_on_in(asyncio_event_loop, monkeypatch):
    counts = {}
    def fake_inc(k, n=1):
        counts[k] = counts.get(k, 0) + n

    monkeypatch.setattr(handler_mod, "inc", fake_inc, raising=False)

    agent = DummyAgent()

    @acl_handler
    async def on_msg(self, acl: AclMessage, raw_msg):
        self.called = True

    acl = AclMessage.build_inform_fact("conv-m1", "budget_total", 999)
    raw = DummyMsg(acl.to_json(), meta={"conversation_id": "conv-m1"})

    asyncio_event_loop.run_until_complete(on_msg(agent, raw))

    assert agent.called is True
    assert counts.get("acl_in_total", 0) == 1
    # performative i type specyficzne
    assert counts.get("acl_in_performative_INFORM", 0) == 1
    assert counts.get("acl_in_type_FACT", 0) == 1
