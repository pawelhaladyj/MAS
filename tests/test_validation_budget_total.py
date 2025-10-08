import json
from collections import deque
from agents.protocol.acl_messages import AclMessage
from agents.coordinator import CoordinatorAgent

class DummyBehaviour: pass

class DummyMsg:
    def __init__(self, sender="presenter@xmpp", meta=None):
        self.sender = sender
        self.metadata = meta or {}

class DummyAgent:
    def __init__(self):
        self.outbox = []
        self._acl_seen_keys = deque(maxlen=64)
    async def send_acl(self, behaviour, acl: AclMessage, to_jid: str):
        self.outbox.append((to_jid, json.loads(acl.to_json())))
    def log(self, *a, **k): pass
    def write_kb_health(self): pass

def test_budget_total_invalid_is_rejected(asyncio_event_loop, monkeypatch):
    agent = DummyAgent()
    beh = DummyBehaviour()
    msg = DummyMsg()

    bad_fact = AclMessage.build_inform_fact("conv-bad-b", "budget_total", "abc", ontology="travel")

    # put_fact nie powinien być wołany dla błędnej wartości
    import agents.coordinator as coord_mod
    monkeypatch.setattr(coord_mod, "put_fact", lambda *a, **k: (_ for _ in ()).throw(AssertionError("put_fact should not be called")), raising=False)

    asyncio_event_loop.run_until_complete(CoordinatorAgent.handle_acl(agent, beh, msg, bad_fact))

    failures = [b for (_to, b) in agent.outbox if b.get("performative") == "FAILURE"]
    assert failures, "expected FAILURE for invalid budget_total"
    assert failures[0]["payload"]["code"] == "VALIDATION_ERROR"

def test_budget_total_valid_is_normalized_and_confirmed(asyncio_event_loop, monkeypatch):
    agent = DummyAgent()
    beh = DummyBehaviour()
    msg = DummyMsg()

    good_fact = AclMessage.build_inform_fact("conv-ok-b", "budget_total", "12 345.67 PLN", ontology="travel")

    calls = []
    import agents.coordinator as coord_mod
    def fake_put_fact(cid, slot, val):
        calls.append((cid, slot, val))
    monkeypatch.setattr(coord_mod, "put_fact", fake_put_fact, raising=False)

    asyncio_event_loop.run_until_complete(CoordinatorAgent.handle_acl(agent, beh, msg, good_fact))

    # zapis do KB z intem
    assert calls and calls[0][0] == "conv-ok-b"
    assert calls[0][1] == "budget_total"
    assert isinstance(calls[0][2]["value"], int)
    assert calls[0][2]["value"] == 12345

    informs = [b for (_to, b) in agent.outbox if b.get("performative") == "INFORM"]
    assert any(b.get("payload", {}).get("type") == "CONFIRM" for b in informs)
