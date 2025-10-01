import asyncio
from typing import Optional

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message

from agents.protocol.acl_messages import AclMessage
from agents.protocol.spade_utils import to_spade_message
from agents.protocol.guards import meta_language_is_json, acl_language_is_json

# (opcjonalnie) integracja z KB dla zdrowia agenta
try:
    from agents.common.kb import put_fact
except Exception:
    put_fact = None


class BaseAgent(Agent):
    """
    Klasa bazowa dla agentów SPADE z ACL:
    - wspólny Inbox (odbiór -> walidacja -> parsowanie -> handle_acl)
    - helpery: send_acl, parse_acl, log
    - prosty healthcheck do KB (jeśli KB dostępne)
    """

    recv_timeout: int = 5   # standardowy timeout na odbiór
    health_session_id: str = "system"

    # ------------ logowanie ------------
    def log(self, msg: str):
        print(f"[{self.__class__.__name__}] {msg}")

    # ------------ ACL helpery ------------
    async def send_acl(self, behaviour, acl: AclMessage, to_jid: str) -> Message:
        """Zbuduj i wyślij SPADE Message z AclMessage (wysyłka przez Behaviour)."""
        msg = to_spade_message(acl, to_jid=to_jid)
        await behaviour.send(msg)
        # Loguj OUT
        try:
            dump = acl.model_dump()
        except AttributeError:
            dump = acl.dict()
        self.log(f"ACL OUT to={to_jid} payload={dump.get('payload')}")
        return msg

    def parse_acl(self, msg: Message) -> Optional[AclMessage]:
        """Wymuś JSON w meta + w obiekcie ACL, potem zwróć AclMessage albo None."""
        if not meta_language_is_json(msg):
            lang_meta = msg.metadata.get("language") if hasattr(msg, "metadata") else None
            self.log(f"WARN unsupported meta.language='{lang_meta}', drop")
            return None

        try:
            acl = AclMessage.from_json(msg.body)  # Pydantic v2
        except AttributeError:
            # Fallback dla Pydantic v1
            import json as _json
            try:
                acl = AclMessage(**_json.loads(msg.body))
            except Exception as e:
                self.log(f"ERR invalid ACL (v1 fallback): {e}; body={msg.body!r}")
                return None
        except Exception as e:
            self.log(f"ERR invalid ACL: {e}; body={msg.body!r}")
            return None

        if not acl_language_is_json(acl):
            try:
                lang = acl.language
            except Exception:
                lang = None
            self.log(f"WARN unsupported ACL.language='{lang}', drop")
            return None

        return acl

    # ------------ Inbox ------------
    class Inbox(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=self.agent.recv_timeout)
            if not msg:
                return

            acl = self.agent.parse_acl(msg)
            if not acl:
                return

            # Loguj IN (po udanym parsowaniu)
            try:
                dump = acl.model_dump()
            except AttributeError:
                dump = acl.dict()
            self.agent.log(f"ACL IN from={str(msg.sender)} payload={dump.get('payload')}")

            # przekaż referencję do aktywnego Behaviour
            await self.agent.handle_acl(self, msg, acl)

    # ------------ Wzorzec: nadpisuj w pochodnych ------------
    async def handle_acl(self, behaviour, spade_msg: Message, acl: AclMessage):
        """Domyślnie tylko log — konkretne agenty nadpisują tę metodę."""
        try:
            dump = acl.model_dump()
        except AttributeError:
            dump = getattr(acl, "dict", lambda: {"_warn": "no-dict"})()
        self.log(f"UNHANDLED ACL payload={dump.get('payload')}")

    # ------------ Healthcheck do KB (opcjonalny) ------------
    def kb_health_slot(self) -> str:
        """Nazwa slotu healthcheck (per-agent)."""
        return f"healthcheck_{self.__class__.__name__.lower()}"

    def kb_health_payload(self) -> dict:
        return {"ok": True}

    def write_kb_health(self):
        if put_fact is None:
            self.log("KB not available, skip healthcheck")
            return
        try:
            put_fact(self.health_session_id, self.kb_health_slot(), self.kb_health_payload())
            self.log("healthcheck saved to KB")
        except Exception as e:
            self.log(f"KB healthcheck FAILED: {e}")

    # ------------ Setup wspólne ------------
    async def setup(self):
        # domyślnie: tylko wspólny inbox
        self.add_behaviour(self.Inbox())
        self.log("starting")

    # ------------ Utility: pętla życia ------------
    @staticmethod
    async def run_forever(agent: "BaseAgent"):
        await agent.start(auto_register=False)
        agent.log("started")
        while True:
            await asyncio.sleep(1)
