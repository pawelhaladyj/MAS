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

def test_nights_invalid_is_rejected(asyncio_event_loop, monkeypatch):
    agent = DummyAgent(); beh = DummyBehaviour(); msg = DummyMsg()
    bad_fact = AclMessage.build_inform_fact("conv-n-bad", "nights", "0")
    import agents.coordinator as coord_mod
    monkeypatch.setattr(coord_mod, "put_fact",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("put_fact should not be called")),
                        raising=False)
    asyncio_event_loop.run_until_complete(CoordinatorAgent.handle_acl(agent, beh, msg, bad_fact))
    fails = [b for (_to,b) in agent.outbox if b.get("performative")=="FAILURE"]
    assert fails and fails[0]["payload"]["code"] == "VALIDATION_ERROR"

def test_nights_valid_is_confirmed(asyncio_event_loop, monkeypatch):
    agent = DummyAgent(); beh = DummyBehaviour(); msg = DummyMsg()
    good_fact = AclMessage.build_inform_fact("conv-n-ok", "nights", "7")
    calls = []
    import agents.coordinator as coord_mod
    def fake_put_fact(cid, slot, val): calls.append((cid, slot, val))
    monkeypatch.setattr(coord_mod, "put_fact", fake_put_fact, raising=False)
    asyncio_event_loop.run_until_complete(CoordinatorAgent.handle_acl(agent, beh, msg, good_fact))
    assert calls and calls[0][0]=="conv-n-ok" and calls[0][1]=="nights" and calls[0][2]["value"]==7
    informs = [b for (_to,b) in agent.outbox if b.get("performative")=="INFORM"]
    assert any(b.get("payload",{}).get("type")=="CONFIRM" for b in informs)
