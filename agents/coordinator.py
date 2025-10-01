import asyncio

from agents.agent import BaseAgent
from agents.common.kb import put_fact
from agents.common.config import settings
from agents.protocol.acl_messages import AclMessage


class CoordinatorAgent(BaseAgent):
    async def handle_acl(self, behaviour, spade_msg, acl: AclMessage):
        payload = acl.payload or {}
        ptype = payload.get("type")

        if ptype == "PING":
            # ACK
            ack = AclMessage.build_inform(
                conversation_id=acl.conversation_id,
                payload={"type": "ACK", "echo": payload},
                ontology=acl.ontology,
            )
            await self.send_acl(behaviour, ack, to_jid=str(spade_msg.sender))
            self.log("acked PING")

            # ASK o budżet (przykład)
            ask = AclMessage.build_request(
                conversation_id=acl.conversation_id,
                payload={"type": "ASK", "need": ["budget_total"], "session_id": acl.conversation_id},
                ontology=acl.ontology,
            )
            await self.send_acl(behaviour, ask, to_jid=str(spade_msg.sender))
            self.log("asked for slot: budget_total")
            return

        if ptype == "FACT":
            slot = payload.get("slot")
            value = payload.get("value")
            source = payload.get("source", "user")
            conv_id = acl.conversation_id

            try:
                put_fact(conv_id, slot, {"value": value, "source": source})
                self.log(f"FACT saved to KB: conv='{conv_id}' slot='{slot}' value='{value}' source='{source}'")

                confirm = AclMessage.build_inform(
                    conversation_id=conv_id,
                    payload={"type": "CONFIRM", "slot": slot, "status": "saved"},
                    ontology=acl.ontology or "default",
                )
                await self.send_acl(behaviour, confirm, to_jid=str(spade_msg.sender))
                self.log(f"confirmed FACT for slot='{slot}'")
            except Exception as e:
                self.log(f"ERR KB write FAILED for slot='{slot}': {e}")
            return

        # Inne typy — dyscyplina: tylko log.
        self.log(f"OTHER payload: {payload}")


async def main():
    a = CoordinatorAgent(
        jid=settings.coordinator_jid,
        password=settings.coordinator_pass,
        verify_security=settings.verify_security,
        # server=settings.xmpp_host,
        # port=settings.xmpp_port,
    )
    a.write_kb_health()
    await BaseAgent.run_forever(a)


if __name__ == "__main__":
    asyncio.run(main())
