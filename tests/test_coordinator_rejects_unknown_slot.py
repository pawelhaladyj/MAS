import json
from collections import deque

from agents.protocol.acl_messages import AclMessage, Performative
from agents.coordinator import CoordinatorAgent


class DummyBehaviour:
    pass

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
    def log(self, *args, **kwargs):
        pass
    def write_kb_health(self):
        pass

def test_unknown_fact_slot_is_rejected(asyncio_event_loop, monkeypatch):
    agent = DummyAgent()
    beh = DummyBehaviour()
    msg = DummyMsg()

    # Nieznany slot
    fact = AclMessage.build_inform_fact("conv-unk", "___not_a_slot___", 1, ontology="travel")

    # put_fact nie powinien być wołany, ale podmieniamy na wszelki wypadek
    import agents.coordinator as coord_mod
    monkeypatch.setattr(coord_mod, "put_fact", lambda *a, **k: (_ for _ in ()).throw(AssertionError("put_fact should not be called")), raising=False)

    asyncio_event_loop.run_until_complete(
        CoordinatorAgent.handle_acl(agent, beh, msg, fact)
    )

    # Powinien wyjść FAILURE/ERROR
    failures = [b for (_to, b) in agent.outbox if b.get("performative") == "FAILURE"]
    assert failures, "expected FAILURE message"
    assert failures[0]["payload"]["type"] == "ERROR"
    assert failures[0]["payload"]["code"] == "VALIDATION_ERROR"
