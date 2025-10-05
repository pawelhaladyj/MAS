import json
import agents.protocol.handler as handler_mod
from agents.protocol import acl_handler
from agents.protocol.acl_messages import AclMessage

class DummyMsg:
    def __init__(self, body, sender="peer@xmpp", meta=None):
        self.body = body
        self.sender = sender
        self.metadata = meta or {}

class DummyBehaviour:
    def __init__(self):
        self.sent = []
        self.acl_handler_timeout = 0.001
        self.acl_max_body_bytes = 64  # bardzo mało
    async def send(self, msg):
        self.sent.append(msg)

def test_metrics_increments_on_body_too_large(asyncio_event_loop, monkeypatch):
    counts = {}
    def fake_inc(k, n=1):
        counts[k] = counts.get(k, 0) + n
    monkeypatch.setattr(handler_mod, "inc", fake_inc, raising=False)

    beh = DummyBehaviour()

    # Zbuduj poprawny ACL, ale wyślij gigantyczny body (większy niż limit)
    acl = AclMessage.build_inform_fact("conv-xl", "budget_total", 999)
    body = acl.to_json() + ("x" * 4096)
    raw = DummyMsg(body, meta={"conversation_id": "conv-xl"})

    @acl_handler
    async def on_msg(self, acl_obj, raw_msg):
        assert False, "handler nie powinien zostać wywołany dla oversized body"

    asyncio_event_loop.run_until_complete(on_msg(beh, raw))
    # Wysłany powinien być FAILURE
    assert beh.sent, "expected a FAILURE reply"
    assert counts.get("acl_in_body_too_large_total", 0) == 1

