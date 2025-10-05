import json
from collections import deque

from agents.protocol.acl_messages import AclMessage
import agents.presenter as presenter_mod

class DummyBehaviour: pass
class DummyMsg:
    def __init__(self, sender="coordinator@xmpp", meta=None):
        self.sender = sender
        self.metadata = meta or {}

class DummyPresenter:
    def __init__(self):
        self.outbox = []
        self._acl_seen_keys = deque(maxlen=64)
    async def send_acl(self, behaviour, acl: AclMessage, to_jid: str):
        self.outbox.append((to_jid, json.loads(acl.to_json())))
    def log(self, *args, **kwargs): pass

def test_presenter_rejects_unknown_ask(asyncio_event_loop):
    agent = DummyPresenter()
    beh = DummyBehaviour()
    msg = DummyMsg(sender="coordinator@xmpp")

    ask = AclMessage.build_request_ask("conv-ask", ["___bad___"], ontology="travel")

    asyncio_event_loop.run_until_complete(
        presenter_mod.PresenterAgent.handle_acl(agent, beh, msg, ask)
    )

    failures = [b for (_to, b) in agent.outbox if b.get("performative") == "FAILURE"]
    assert failures
    assert failures[0]["payload"]["code"] == "VALIDATION_ERROR"
