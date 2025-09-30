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

            # Parsowanie JSON z ostrożnością
            try:
                data = json.loads(msg.body)
            except Exception as e:
                print(f"[Coordinator] bad json: {e}; body={msg.body!r}")
                return

            print(f"[Coordinator] got:", data)
            t = data.get("type")

            if t == "PING":
                # Zapisz handshake do KB
                session_id = data.get("session_id", "s-unk")
                add_fact(session_id, "handshake", "received", source="presenter")

                # ACK jak wcześniej
                reply = Message(to=str(msg.sender))
                reply.set_metadata("performative", "INFORM")
                reply.body = json.dumps({"type": "ACK", "echo": data})
                await self.send(reply)

                # Policz braki i poproś o pierwszy brakujący slot
                need = missing_slots(session_id)
                if need:
                    ask = Message(to=str(msg.sender))
                    ask.set_metadata("performative", "INFORM")
                    ask.body = json.dumps({
                        "type": "ASK",
                        "need": need[:1],
                        "session_id": session_id,
                    })
                    await self.send(ask)
                    available = [s for s in REQUIRED_SLOTS if get_fact(session_id, s) is not None]
                    print(f"[Coordinator] facts={len(available)} missing={len(need)}")

            elif t == "FACT":
                # Zapisz fakt od użytkownika do KB
                session_id = data.get("session_id", "s-unk")
                slot = data.get("slot")
                value = data.get("value")
                source = data.get("source", "user")

                if slot is not None:
                    add_fact(session_id, slot, value, source=source)

                # Ponownie policz braki – dopytaj lub zakończ
                need = missing_slots(session_id)
                if need:
                    ask = Message(to=str(msg.sender))
                    ask.set_metadata("performative", "INFORM")
                    ask.body = json.dumps({
                        "type": "ASK",
                        "need": need[:1],
                        "session_id": session_id,
                    })
                    await self.send(ask)
                    available = [s for s in REQUIRED_SLOTS if get_fact(session_id, s) is not None]
                    print(f"[Coordinator] facts={len(available)} missing={len(need)}")
                else:
                    print(f"[Coordinator] All required slots collected for {session_id}.")
                    # MOCK: zapisz przykładową ofertę do KB
                    add_offer(
                        session_id,
                        provider="mock-hotel",
                        offer={"hotel": "Aqua Palace", "city": "Hurghada", "stars": 5, "board": "AI", "price_pln": 9999},
                        score=0.95,
                    )
                    # pokaż top oferty z KB
                    top = query_offers(session_id)
                    print(f"[Coordinator] top offers -> {top[:1]}")

            else:
                # Inne typy na później
                pass

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
