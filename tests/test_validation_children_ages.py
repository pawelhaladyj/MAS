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

def test_children_ages_invalid_is_rejected(asyncio_event_loop, monkeypatch):
    agent = DummyAgent(); beh = DummyBehaviour(); msg = DummyMsg()
    bad_cases = ["", "18, -1", ["x", 5], 123]
    import agents.coordinator as coord_mod
    monkeypatch.setattr(
        coord_mod, "put_fact",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("put_fact should not be called")),
        raising=False
    )
    for i, v in enumerate(bad_cases):
        agent.outbox.clear()
        fact = AclMessage.build_inform_fact(f"conv-ages-bad-{i}", "party_children_ages", v)
        asyncio_event_loop.run_until_complete(CoordinatorAgent.handle_acl(agent, beh, msg, fact))
        fails = [b for (_to,b) in agent.outbox if b.get("performative")=="FAILURE"]
        assert fails and fails[0]["payload"]["code"] == "VALIDATION_ERROR"

def test_children_ages_valid_variants(asyncio_event_loop, monkeypatch):
    agent = DummyAgent(); beh = DummyBehaviour(); msg = DummyMsg()
    good_cases = [
        ("13,11", [13,11]),
        ("5 7 9", [5,7,9]),
        ("4; 6", [4,6]),
        ([0, 17], [0,17]),
        (["3","10"], [3,10]),
    ]
    calls = []
    import agents.coordinator as coord_mod
    def fake_put_fact(cid, slot, val): calls.append((cid, slot, val))
    monkeypatch.setattr(coord_mod, "put_fact", fake_put_fact, raising=False)

    for i, (input_v, expected) in enumerate(good_cases):
        calls.clear(); agent.outbox.clear()
        fact = AclMessage.build_inform_fact(f"conv-ages-ok-{i}", "party_children_ages", input_v)
        asyncio_event_loop.run_until_complete(CoordinatorAgent.handle_acl(agent, beh, msg, fact))
        assert calls and calls[0][1]=="party_children_ages"
        assert calls[0][2]["value"] == expected
        informs = [b for (_to,b) in agent.outbox if b.get("performative")=="INFORM"]
        assert any(b.get("payload",{}).get("type")=="CONFIRM" for b in informs)
