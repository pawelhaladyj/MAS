import json

import asyncio
from typing import Optional
from datetime import datetime, timezone

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message

from agents.protocol.acl_messages import AclMessage
from agents.protocol.guards import meta_language_is_json, acl_language_is_json
from agents.common.telemetry import log_acl_event
from agents.common.metrics import inc
from agents.common.metrics import export_to_kb


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
        
    def wire_log(self, dir_: str, *, acl: AclMessage, to_jid: Optional[str]=None, spade_msg: Optional[Message]=None):
        try:
            from_jid = str(getattr(spade_msg, "sender", self.jid))
            thr   = getattr(spade_msg, "thread", None) if spade_msg else None
            meta  = getattr(spade_msg, "metadata", {}) or {}
            stanza = getattr(spade_msg, "id", None) or meta.get("stanza_id")
            ptype = (acl.payload or {}).get("type")
            sess  = (acl.payload or {}).get("session_id")
            self.log(
                "WIRE "
                f"dir={dir_} from={from_jid} to={to_jid or ''} "
                f"perf={getattr(acl.performative,'value',str(acl.performative))} type={ptype} "
                f"conv={acl.conversation_id} sess={sess} thread={thr} stanza={stanza} "
                f"ts={datetime.now(timezone.utc).isoformat()}"
            )
        except Exception:
            pass


    # ------------ ACL helpery ------------
    async def send_acl(self, behaviour, acl: AclMessage, to_jid: str) -> Message:
        """Zbuduj i wyślij SPADE Message z AclMessage (wysyłka przez Behaviour)."""

        # 1) Budowa SPADE Message z gwarancją: thread == conversation_id
        #    (używamy metody z AclMessage dodanej w poprzednim kroku)
        msg = acl.to_spade_message(to=to_jid)

        # 2) Pas bezpieczeństwa (nawet gdyby ktoś zbudował msg inną ścieżką):
        if not getattr(msg, "thread", None):
            msg.thread = acl.conversation_id
        elif msg.thread != acl.conversation_id:
            self.log(f"[warn] Overriding thread {msg.thread!r} -> {acl.conversation_id!r}")
            msg.thread = acl.conversation_id

        # 3) Krótka telemetria „przewozowa” — jednorodna
        try:
            pval = getattr(acl.performative, "value", str(acl.performative))
            ptype = (acl.payload or {}).get("type")
            sess  = (acl.payload or {}).get("session_id")
            self.log(
                "WIRE dir=OUT "
                f"from={self.jid} to={to_jid} "
                f"perf={pval} type={ptype} "
                f"conv={acl.conversation_id} sess={sess} "
                f"thread={getattr(msg, 'thread', None)} stanza=None "
                f"ts={datetime.now(timezone.utc).isoformat()}"
            )
        except Exception:
            pass

        # 4) TELEMETRIA OUT (jak było)
        try:
            log_acl_event(acl.conversation_id, "OUT", json.loads(acl.to_json()))
        except Exception as e:
            self.log(f"[telemetry] OUT failed: {e}")

        # 5) METRYKI OUT (jak było)
        try:
            inc("acl_out_total", 1)
            p = getattr(acl, "performative", None)
            if p and getattr(p, "value", None):
                inc(f"acl_out_performative_{p.value}", 1)
            payload = getattr(acl, "payload", {}) or {}
            ptype = payload.get("type")
            if isinstance(ptype, str):
                inc(f"acl_out_type_{ptype}", 1)
        except Exception:
            pass

        # 6) Właściwa wysyłka
        await behaviour.send(msg)

        # 7) Log „po wysyłce” (jak było)
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
            # parser respektujący XMPP thread (dokładaliśmy go w AclMessage)
            acl = AclMessage.from_spade_message(msg)
        except Exception as e:
            self.log(f"ERR invalid ACL (from_spade_message): {e}; body={getattr(msg,'body', '')!r}")
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

            # WIRE IN (jednolinijkowy log do debugowania spójności)
            try:
                ptype = (acl.payload or {}).get("type")
                sess  = (acl.payload or {}).get("session_id")
                thr   = getattr(msg, "thread", None)
                meta  = getattr(msg, "metadata", {}) or {}
                stanza = getattr(msg, "id", None) or meta.get("stanza_id")
                self.agent.log(
                    "WIRE dir=IN "
                    f"from={str(getattr(msg, 'sender', ''))} "
                    f"perf={getattr(acl.performative,'value',str(acl.performative))} type={ptype} "
                    f"conv={acl.conversation_id} sess={sess} thread={thr} stanza={stanza} "
                    f"ts={datetime.now(timezone.utc).isoformat()}"
                )
            except Exception:
                pass


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
            
    def export_metrics(self, session_id: str = "system", slot_prefix: str = "metrics") -> str:
        try:
            slot = export_to_kb(session_id=session_id, slot_prefix=slot_prefix)
            self.log(f"metrics exported to KB slot='{slot}'")
            return slot
        except Exception as e:
            self.log(f"metrics export FAILED: {e}")
            return ""

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
