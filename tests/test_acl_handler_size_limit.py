# tests/test_acl_handler_size_limit.py
import json

from agents.protocol import acl_handler
from agents.protocol.acl_messages import AclMessage


class DummyMsg:
    def __init__(self, body: str, sender: str = "peer@xmpp", metadata: dict | None = None):
        self.body = body
        self.sender = sender
        self.metadata = metadata or {}


class DummyAgent:
    def __init__(self):
        self.outbox = []
        self.called = False
        # ustawiamy mały limit, by łatwo przetestować
        self.acl_max_body_bytes = 256

    async def send(self, msg):
        # msg ma atrybut body (SPADE Message) – my sprawdzimy tylko JSON w body
        self.outbox.append(msg)

def test_acl_handler_rejects_too_large_body(asyncio_event_loop):
    agent = DummyAgent()

    @acl_handler
    async def on_msg(self, acl: AclMessage, raw_msg):
        # nie powinno się wykonać przy zbyt dużym body
        self.called = True

    # zbuduj body większe niż 256 B
    big_payload = {"type": "FACT", "slot": "budget_total", "value": "X" * 300}
    acl = AclMessage.build_inform("conv-big", big_payload)
    raw = DummyMsg(acl.to_json(), sender="peer@xmpp", metadata={"conversation_id": "conv-big"})

    asyncio_event_loop.run_until_complete(on_msg(agent, raw))

    # nie wywołano logiki
    assert agent.called is False

    # wysłano FAILURE
    assert len(agent.outbox) == 1
    body = getattr(agent.outbox[0], "body", "")
    data = json.loads(body)
    assert data["performative"] == "FAILURE"
    assert data["payload"]["type"] == "ERROR"
    assert data["payload"]["code"] == "VALIDATION_ERROR"
    assert data["conversation_id"] == "conv-big"
    assert data["payload"]["details"]["max_bytes"] == 256
