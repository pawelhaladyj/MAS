import agents.protocol.handler as handler_mod
from agents.protocol import acl_handler

class DummyMsg:
    def __init__(self, body, sender="peer@xmpp", meta=None):
        self.body = body
        self.sender = sender
        self.metadata = meta or {}

class DummyBehaviour:
    def __init__(self):
        self.sent = []
        self.acl_handler_timeout = 0.001
    async def send(self, msg):
        self.sent.append(msg)

def test_metrics_increments_on_validation_error(asyncio_event_loop, monkeypatch):
    counts = {}
    def fake_inc(k, n=1):
        counts[k] = counts.get(k, 0) + n
    monkeypatch.setattr(handler_mod, "inc", fake_inc, raising=False)

    beh = DummyBehaviour()

    # Body nie-JSON → validate_acl_json zwróci not ok
    raw = DummyMsg("{this is not json", meta={"conversation_id": "conv-bad"})

    @acl_handler
    async def on_msg(self, acl_obj, raw_msg):
        assert False, "handler nie powinien wejść przy invalid json"

    asyncio_event_loop.run_until_complete(on_msg(beh, raw))
    assert beh.sent, "expected a FAILURE reply for invalid JSON"
    assert counts.get("acl_in_validation_errors_total", 0) == 1

