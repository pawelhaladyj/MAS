import agents.presenter as presenter_mod
from agents.protocol.acl_messages import AclMessage

class DummyBehaviour: ...
class DummyMsg:
    def __init__(self, sender="coordinator@xmpp", meta=None):
        self.sender = sender
        self.metadata = meta or {}

class DummyPresenter:
    def __init__(self):
        self.outbox = []
        self._acl_seen_keys = __import__("collections").deque(maxlen=64)
    async def send_acl(self, behaviour, acl, to_jid: str):
        import json
        self.outbox.append((to_jid, json.loads(acl.to_json())))
    def log(self, *a, **k): pass

def test_presenter_sets_state_gather_on_ask(asyncio_event_loop, monkeypatch):
    agent = DummyPresenter()
    beh = DummyBehaviour()

    # Włącz DEMO_AUTOFILL -> presenter wyśle FACT po ASK
    monkeypatch.setenv("DEMO_AUTOFILL", "1")

    # ASK od koordynatora
    ask = AclMessage.build_request_ask(
        conversation_id="conv-fsm",
        need=["budget_total"],
        ontology="travel",
    )
    ask.payload["session_id"] = "conv-fsm"
    msg = DummyMsg(sender="coordinator@xmpp", meta={"conversation_id": "conv-fsm"})

    # Patch: zapis stanu sesji do KB
    calls = []
    def fake_put_fact(conv_id, slot, value):
        calls.append((conv_id, slot, value))
    monkeypatch.setattr(presenter_mod, "put_fact", fake_put_fact, raising=False)

    # Run
    asyncio_event_loop.run_until_complete(
        presenter_mod.PresenterAgent.handle_acl(agent, beh, msg, ask)
    )

    # 1) FSM → GATHER
    assert ("conv-fsm", "session_state", {"value": "GATHER"}) in calls

    # 2) W trybie demo wyszedł FACT (dla budżetu)
    sent = [b for (_to, b) in agent.outbox if b.get("payload", {}).get("type") == "FACT"]
    assert sent and sent[0]["payload"]["slot"] == "budget_total"
