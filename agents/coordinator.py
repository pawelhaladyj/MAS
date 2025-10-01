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
                print("[Coordinator] ACL IN:", acl_in.model_dump())
            except Exception as e:
                print("[Coordinator] invalid ACL:", e)
                return

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
