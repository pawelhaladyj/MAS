from agents.protocol import AclMessage, Performative, acl_handler
from agents.protocol.spade_utils import to_spade_message

# --- atrapy ---

class DummyMsg:
    def __init__(self, body: str, sender: str = "coordinator@xmpp", metadata: dict | None = None):
        self.body = body
        self.sender = sender
        self.metadata = metadata or {}

class DummyAgent:
    def __init__(self):
        self.outbox = []  # zbieramy wysłane wiadomości

    async def send(self, msg):
        # w prawdziwym SPADE `msg` ma .body i .metadata; tu wystarczy zachować dla asercji
        self.outbox.append(msg)

# --- testy ---

import json
import pytest

def test_acl_handler_ok_path(asyncio_event_loop):
    agent = DummyAgent()

    @acl_handler
    async def on_msg(self, acl: AclMessage, raw_msg):
        # zwrotnie wyślij ACK (sprawdzimy, że handler dostał poprawny ACL)
        reply = AclMessage.build_inform_ack(acl.conversation_id, {"type": "PING"})
        await self.send(to_spade_message(reply, raw_msg.sender))

    # poprawna wiadomość
    src = AclMessage.build_request_ask("conv-42", ["dates", "party_size"], ontology="travel")
    msg = DummyMsg(src.to_json(), sender="coordinator@xmpp", metadata={"conversation_id": "conv-42"})

    # odpal „handler”
    asyncio_event_loop.run_until_complete(on_msg(agent, msg))

    # sprawdź odpowiedź w outbox
    assert len(agent.outbox) == 1
    sent = agent.outbox[0]
    # w spade_utils to jest obiekt Message; w teście wystarczy sprawdzić body JSON
    body = getattr(sent, "body", None)
    assert body is not None
    parsed = json.loads(body)
    assert parsed["performative"] == "INFORM"
    assert parsed["payload"]["type"] == "ACK"
    assert parsed["conversation_id"] == "conv-42"

def test_acl_handler_validation_error_sends_failure(asyncio_event_loop):
    agent = DummyAgent()

    @acl_handler
    async def on_msg(self, acl: AclMessage, raw_msg):
        # nie powinno się wykonać dla złej wiadomości
        raise AssertionError("Handler should not be called on invalid message")

    # niepoprawny JSON + conversation_id w meta dla fallbacku
    bad = DummyMsg("{not-json", sender="coordinator@xmpp", metadata={"conversation_id": "conv-bad"})
    asyncio_event_loop.run_until_complete(on_msg(agent, bad))

    # sprawdzamy, że poszedł FAILURE/ERROR do nadawcy
    assert len(agent.outbox) == 1
    body = getattr(agent.outbox[0], "body", None)
    data = json.loads(body)
    assert data["performative"] == "FAILURE"
    assert data["payload"]["type"] == "ERROR"
    assert data["conversation_id"] == "conv-bad"
