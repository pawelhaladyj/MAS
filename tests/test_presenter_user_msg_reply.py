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
    def __init__(self):
        self.outbox = []
        self._acl_seen_keys = deque(maxlen=64)
    async def send_acl(self, behaviour, acl: AclMessage, to_jid: str):
        self.outbox.append((to_jid, json.loads(acl.to_json())))
    def log(self, *args, **kwargs):
        pass

def test_presenter_replies_to_user_msg(asyncio_event_loop):
    agent = DummyPresenter()
    beh = DummyBehaviour()
    msg = DummyMsg(sender="bridge@xmpp", meta={"conversation_id": "conv-chat"})

    user = AclMessage.build_request_user_msg(
        conversation_id="conv-chat",
        text="Cześć, lecimy w lutym?",
        ontology="ui",
        session_id="conv-chat",
    )

    asyncio_event_loop.run_until_complete(
        presenter_mod.PresenterAgent.handle_acl(agent, beh, msg, user)
    )

    replies = [b for (_to, b) in agent.outbox if b.get("payload", {}).get("type") == "PRESENTER_REPLY"]
    assert replies, "Presenter should reply with PRESENTER_REPLY"
    assert "Cześć" in replies[0]["payload"]["text"] or "Brzmi spoko" in replies[0]["payload"]["text"]
