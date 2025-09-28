import json, asyncio
from spade.agent import Agent
from spade.behaviour import OneShotBehaviour, CyclicBehaviour
from spade.message import Message
from agents.common.config import settings

class PresenterAgent(Agent):
    class Kickoff(OneShotBehaviour):
        async def run(self):
            msg = Message(to=settings.coordinator_jid)
            msg.set_metadata("performative","REQUEST")
            msg.body = json.dumps({"type":"PING","session_id":"demo-1"})
            await self.send(msg)
            print("[Presenter] sent PING")

    class Inbox(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=10)
            if not msg: return
            data = json.loads(msg.body)
            print(f"[Presenter] got:", data)

    async def setup(self):
        print("[Presenter] starting")
        self.add_behaviour(self.Kickoff())
        self.add_behaviour(self.Inbox())

async def main():
    a = PresenterAgent(
        jid=settings.presenter_jid,
        password=settings.presenter_pass,
        verify_security=settings.verify_security,
    )
    await a.start(auto_register=False)
    print("[Presenter] started")
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
