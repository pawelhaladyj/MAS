import json
from collections import deque

from agents.coordinator import CoordinatorAgent
from agents.protocol.acl_messages import AclMessage

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

    # hook z BaseAgent – będziemy monkeypatchować w teście
    def export_metrics(self, session_id="system", slot_prefix="metrics"):
        return f"{slot_prefix}_dummy123"

def test_metrics_export_request_produces_confirm(asyncio_event_loop, monkeypatch):
    agent = DummyAgent()
    beh = DummyBehaviour()
    msg = DummyMsg()

    # REQUEST o eksport metryk
    req = AclMessage.build_request(
        conversation_id="conv-mexp",
        payload={"type": "METRICS_EXPORT"},
        ontology="system",
    )

    asyncio_event_loop.run_until_complete(
        CoordinatorAgent.handle_acl(agent, beh, msg, req)
    )

    # Oczekujemy INFORM/CONFIRM z nazwą slotu w statusie
    informs = [b for (_to, b) in agent.outbox if b.get("performative") == "INFORM"]
    assert informs, "expected INFORM as confirmation"
    p = informs[0].get("payload", {})
    assert p.get("type") == "CONFIRM"
    assert p.get("slot") == "metrics_export"
    assert isinstance(p.get("status"), str) and p["status"].startswith("metrics_")
