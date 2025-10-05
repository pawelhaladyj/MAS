import agents.agent as agent_mod
from agents.protocol.acl_messages import AclMessage

class DummyBehaviour:
    def __init__(self):
        self.sent = []
    async def send(self, msg):
        self.sent.append(msg)

class DummySelf:
    def log(self, *a, **k): pass
    async def send(self, msg): pass

def test_metrics_increment_on_out(asyncio_event_loop, monkeypatch):
    counts = {}
    def fake_inc(k, n=1):
        counts[k] = counts.get(k, 0) + n

    monkeypatch.setattr(agent_mod, "inc", fake_inc, raising=False)

    beh = DummyBehaviour()
    self = DummySelf()
    acl = AclMessage.build_request_ask("conv-m2", ["nights"])

    asyncio_event_loop.run_until_complete(
        agent_mod.BaseAgent.send_acl(self, beh, acl, to_jid="peer@xmpp")
    )

    assert counts.get("acl_out_total", 0) == 1
    assert counts.get("acl_out_performative_REQUEST", 0) == 1
    assert counts.get("acl_out_type_ASK", 0) == 1
    assert beh.sent, "message should be sent"
