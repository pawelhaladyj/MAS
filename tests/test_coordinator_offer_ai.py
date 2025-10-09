import json
from collections import deque

import os
import agents.coordinator as coord_mod
from agents.protocol.acl_messages import AclMessage

class DummyBehaviour: pass

class DummyMsg:
    def __init__(self, sender="presenter@xmpp", meta=None):
        self.sender = sender
        self.metadata = meta or {"conversation_id": "conv-ai"}

class DummyAgent:
    def __init__(self):
        self.outbox = []
        self._acl_seen_keys = deque(maxlen=64)
    async def send_acl(self, behaviour, acl: AclMessage, to_jid: str):
        self.outbox.append((to_jid, json.loads(acl.to_json())))
    def log(self, *a, **k): pass
    def write_kb_health(self): pass

def _run(agent, beh, msg, acl, loop):
    loop.run_until_complete(coord_mod.CoordinatorAgent.handle_acl(agent, beh, msg, acl))

def test_offer_uses_ai_when_enabled(asyncio_event_loop, monkeypatch):
    agent = DummyAgent()
    beh = DummyBehaviour()
    msg = DummyMsg()

    # Włącz AI i podstaw chat_reply
    monkeypatch.setenv("AI_ENABLED", "1")
    import ai.openai_client as ai_mod
    monkeypatch.setattr(ai_mod, "chat_reply", lambda system_prompt, user_text: "Proponuję Sardynię w czerwcu — co Ty na to?", raising=False)

    ping = AclMessage.build_request("conv-ai", {"type": "PING"}, ontology="default")
    _run(agent, beh, msg, ping, asyncio_event_loop)

    offers = [b for (_to, b) in agent.outbox if b.get("payload", {}).get("type") == "OFFER"]
    assert offers, "expected OFFER to be sent"
    notes = offers[0]["payload"]["proposal"]["notes"]
    assert "Sardynię" in notes or "Sardynię" in notes

def test_offer_fallback_without_ai(asyncio_event_loop, monkeypatch):
    agent = DummyAgent()
    beh = DummyBehaviour()
    msg = DummyMsg()

    # Wyłącz AI
    monkeypatch.setenv("AI_ENABLED", "0")
    # upewnij się, że nawet jeśli chat_reply by istniało, nic nie wołamy — brak patcha tutaj

    ping = AclMessage.build_request("conv-ai2", {"type": "PING"}, ontology="default")
    _run(agent, beh, msg, ping, asyncio_event_loop)

    offers = [b for (_to, b) in agent.outbox if b.get("payload", {}).get("type") == "OFFER"]
    assert offers, "expected OFFER to be sent"
    notes = offers[0]["payload"]["proposal"]["notes"]
    assert "Luźna podpowiedź" in notes
