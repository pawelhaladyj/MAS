# tests/test_coordinator_fact_confirm.py
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
    """Lekka atrapa 'self' dla CoordinatorAgent.handle_acl.
    Wystarczą: send_acl, log, outbox i bufor deduplikacji.
    """
    def __init__(self):
        self.outbox = []
        self._acl_seen_keys = deque(maxlen=64)

    async def send_acl(self, behaviour, acl: AclMessage, to_jid: str):
        # Zbieramy wysyłane ramki do asercji
        self.outbox.append((to_jid, json.loads(acl.to_json())))

    def log(self, *args, **kwargs):
        pass

    def write_kb_health(self):
        pass


def test_coordinator_fact_produces_confirm(asyncio_event_loop, monkeypatch):
    agent = DummyAgent()
    beh = DummyBehaviour()

    # Wejściowy FACT (jak od Presentera)
    fact = AclMessage.build_inform_fact("conv-t1", "budget_total", 12345, ontology="travel")
    msg = DummyMsg(sender="presenter@xmpp", meta={"conversation_id": "conv-t1"})

    # Monkeypatch: podmień put_fact dokładnie w module koordynatora
    import agents.coordinator as coord_mod
    calls = []

    def fake_put_fact(conv_id, slot, value):
        calls.append((conv_id, slot, value))

    monkeypatch.setattr(coord_mod, "put_fact", fake_put_fact, raising=False)

    # Uruchom asynchroniczną metodę bez pytest-asyncio (używamy lokalnego fixture loopa)
    asyncio_event_loop.run_until_complete(
        CoordinatorAgent.handle_acl(agent, beh, msg, fact)
    )

    # 1) zapis do KB był wywołany
    assert calls and calls[0][0] == "conv-t1"

    # 2) w outboxie jest INFORM z payload.type == CONFIRM
    sent_informs = [body for _to, body in agent.outbox if body.get("performative") == "INFORM"]
    assert any(b.get("payload", {}).get("type") == "CONFIRM" for b in sent_informs)
