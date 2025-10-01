# agents/coordinator.py
import json
import asyncio
from typing import Optional

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message

from agents.common.config import settings
from agents.common.kb import put_fact, get_fact, query_offers, add_offer
from agents.common.slots import REQUIRED_SLOTS
from agents.protocol.acl_messages import AclMessage


def add_fact(session_id: str, slot: str, value, source: str = "system"):
    """Adapter na put_fact: zapisuje fakt do KB w standardowym formacie."""
    if not isinstance(value, dict):
        value = {"value": value}
    value["source"] = source
    put_fact(session_id, slot, value)


def missing_slots(session_id: str):
    """Zwraca listę brakujących slotów (sprawdza każdy przez get_fact)."""
    missing = []
    for s in REQUIRED_SLOTS:
        if get_fact(session_id, s) is None:
            missing.append(s)
    return missing


class CoordinatorAgent(Agent):
    class Inbox(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=5)
            if not msg:
                return

            try:
                acl_in = AclMessage.from_json(msg.body)
                print("[Coordinator] ACL IN:", acl_in.model_dump())  # lub .dict() przy v1 fallback
            except Exception as e:
                print("[Coordinator] invalid ACL:", e)
                return

            # NOWE: jeśli to PING, odsyłamy ACK w ACL
            if acl_in.payload.get("type") == "PING":
                acl_out = AclMessage.build_inform(
                    conversation_id=acl_in.conversation_id,
                    payload={"type": "ACK", "echo": acl_in.payload},
                    ontology=acl_in.ontology,
                )

                reply = Message(to=str(msg.sender))
                reply.set_metadata("performative", acl_out.performative.value)
                reply.set_metadata("conversation_id", acl_out.conversation_id)
                reply.set_metadata("ontology", acl_out.ontology)
                reply.set_metadata("language", acl_out.language)
                reply.body = acl_out.to_json()

                await self.send(reply)
                print("[Coordinator] acked PING")
                
                # Testowe ASK: prosimy o jeden slot (np. budget_total)
                ask_acl = AclMessage.build_request(
                    conversation_id=acl_in.conversation_id,
                    payload={"type": "ASK", "need": ["budget_total"], "session_id": acl_in.conversation_id},
                    ontology=acl_in.ontology,
                )
                ask = Message(to=str(msg.sender))
                ask.set_metadata("performative", ask_acl.performative.value)
                ask.set_metadata("conversation_id", ask_acl.conversation_id)
                ask.set_metadata("ontology", ask_acl.ontology)
                ask.set_metadata("language", ask_acl.language)
                ask.body = ask_acl.to_json()
                await self.send(ask)
                print("[Coordinator] asked for slot: budget_total")
                
            # 3) NOWE: odbiór FACT (ACL)
            elif acl_in.payload.get("type") == "FACT":
                slot = acl_in.payload.get("slot")
                value = acl_in.payload.get("value")
                source = acl_in.payload.get("source", "user")
                conv_id = acl_in.conversation_id  # sesja z nagłówka ACL

                try:
                    # zapis do KB: kluczem jest nazwa slotu, wartością słownik z value/source
                    put_fact(conv_id, slot, {"value": value, "source": source})
                    print(f"[Coordinator] FACT saved to KB: conv='{conv_id}' slot='{slot}' value='{value}' source='{source}'")
                except Exception as e:
                    print(f"[Coordinator] KB write FAILED for slot='{slot}':", e)

    async def setup(self):
        print("[Coordinator] starting")
        self.add_behaviour(self.Inbox())


async def main():
    a = CoordinatorAgent(
        jid=settings.coordinator_jid,
        password=settings.coordinator_pass,
        verify_security=settings.verify_security,
        # server=settings.xmpp_host,
        # port=settings.xmpp_port,
    )
    await a.start(auto_register=True)
    print("[Coordinator] started")
    while True:
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
