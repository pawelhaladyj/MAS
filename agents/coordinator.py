import json, asyncio
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from agents.common.config import settings

class CoordinatorAgent(Agent):
    class Inbox(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=5)
            if not msg: return
            data = json.loads(msg.body)
            print(f"[Coordinator] got:", data)
            reply = Message(to=str(msg.sender))
            reply.set_metadata("performative","INFORM")
            reply.body = json.dumps({"type":"ACK","echo":data})
            await self.send(reply)

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
