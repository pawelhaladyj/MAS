
# tests/test_presenter_fsm.py
import json
from collections import deque

from agents.protocol.acl_messages import AclMessage
import agents.presenter as presenter_mod


class DummyBehaviour:
    pass


class DummyMsg:
    def __init__(self, sender="coordinator@xmpp", meta=None):
        self.sender = sender
        self.metadata = meta or {}


class DummyPresenter:
    """Atrapa PresenterAgent do testu handle_acl – tylko to, czego potrzebujemy."""
    def __init__(self):
        self.outbox = []
        self.log_calls = []
        # ⬇⬇⬇ DODANE: zgodnie z implementacją deduplikacji w PresenterAgent
        self._acl_seen_keys = deque(maxlen=64)

    async def send_acl(self, behaviour, acl: AclMessage, to_jid: str):
        self.outbox.append((to_jid, json.loads(acl.to_json())))

    def log(self, *args, **kwargs):
        self.log_calls.append((args, kwargs))


def test_presenter_sets_state_gather_on_ask(asyncio_event_loop, monkeypatch):
    agent = DummyPresenter()
    beh = DummyBehaviour()

    # ASK od koordynatora
    ask = AclMessage.build_request_ask(
        conversation_id="conv-fsm",
        need=["budget_total"],
        ontology="travel",
    )
    # Koordynator przekazuje zwykle session_id w payloadzie
    ask.payload["session_id"] = "conv-fsm"
    msg = DummyMsg(sender="coordinator@xmpp", meta={"conversation_id": "conv-fsm"})

    # Podmień zapis do KB tylko dla set_session_state (helper w module presenterskim)
    calls = []

    def fake_put_fact(conv_id, slot, value):
        calls.append((conv_id, slot, value))

    monkeypatch.setattr(presenter_mod, "put_fact", fake_put_fact, raising=False)

    # Uruchom handle_acl (bez realnego XMPP)
    asyncio_event_loop.run_until_complete(
        presenter_mod.PresenterAgent.handle_acl(agent, beh, msg, ask)
    )

    # 1) stan FSM zapisany do KB jako GATHER
    assert ("conv-fsm", "session_state", {"value": "GATHER"}) in calls

    # 2) wyszła odpowiedź FACT do koordynatora (kontynuacja dialogu)
    sent = [b for (_to, b) in agent.outbox if b.get("payload", {}).get("type") == "FACT"]
    assert sent and sent[0]["payload"]["slot"] == "budget_total"
