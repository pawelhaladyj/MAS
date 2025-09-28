import json, asyncio
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from agents.common.config import settings
from agents.common.kb import kb, Fact
from agents.common.slots import REQUIRED_SLOTS

def missing_slots(session_id: str):
    """Zwraca listę brakujących slotów dla danej sesji."""
    facts = kb.get_session(session_id)
    got = {f.slot for f in facts}
    return [s for s in REQUIRED_SLOTS if s not in got]

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
                kb.add(Fact(session_id=session_id, slot="handshake",
                            value="received", source="presenter"))

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
                    print(f"[Coordinator] facts={len(kb.get_session(session_id))} missing={len(need)}")

            elif t == "FACT":
                # Zapisz fakt od użytkownika do KB
                session_id = data.get("session_id", "s-unk")
                slot = data.get("slot")
                value = data.get("value")
                source = data.get("source", "user")

                if slot is not None:
                    kb.add(Fact(session_id=session_id, slot=slot, value=value, source=source))

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
                    print(f"[Coordinator] facts={len(kb.get_session(session_id))} missing={len(need)}")
                else:
                    print(f"[Coordinator] All required slots collected for {session_id}.")
                    # tu w kolejnych etapach wyślesz cele do specjalistów (flights/hotels/weather/ranker)

            else:
                # inne typy na później
                pass

    async def setup(self):
        print("[Coordinator] starting")
        self.add_behaviour(self.Inbox())

async def main():
    a = CoordinatorAgent(
        jid=settings.coordinator_jid,
        password=settings.coordinator_pass,
        verify_security=settings.verify_security,
    )
    await a.start(auto_register=False)
    print("[Coordinator] started")
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
