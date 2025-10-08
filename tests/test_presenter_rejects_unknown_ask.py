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

def test_presenter_handles_unknown_ask_without_failure(asyncio_event_loop, monkeypatch):
    agent = DummyPresenter()
    beh = DummyBehaviour()
    msg = DummyMsg(sender="coordinator@xmpp")

    # Upewnij się, że DEMO_AUTOFILL jest wyłączony -> nie wyśle FACT
    monkeypatch.delenv("DEMO_AUTOFILL", raising=False)

    ask = AclMessage.build_request_ask("conv-ask", ["___bad___"], ontology="travel")

    asyncio_event_loop.run_until_complete(
        presenter_mod.PresenterAgent.handle_acl(agent, beh, msg, ask)
    )

    # Nie wysyłamy FAILURE ani FACT; prezentujemy tylko podpowiedź dla człowieka (log)
    assert not any(b.get("performative") == "FAILURE" for (_to, b) in agent.outbox)
    assert not any(b.get("payload", {}).get("type") == "FACT" for (_to, b) in agent.outbox)
