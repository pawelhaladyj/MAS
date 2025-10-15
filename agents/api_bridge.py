# agents/api_bridge.py
import asyncio
import json
from typing import Dict, Optional
import contextlib

from agents.agent import BaseAgent
from agents.common.config import settings
from agents.protocol.acl_messages import AclMessage
from agents.protocol import acl_handler
from agents.protocol.guards import acl_language_is_json
from spade.behaviour import CyclicBehaviour

class ApiBridgeAgent(BaseAgent):
    def __init__(self, *args, inbox: asyncio.Queue, outbox: asyncio.Queue, **kwargs):
        super().__init__(*args, **kwargs)
        self.inbox = inbox
        self.outbox = outbox
        # per-session „waiters” – HTTP będzie czekał na tę kolejkę
        self._http_waiters: Dict[str, asyncio.Queue] = {}
        self._http_buffer: Dict[str, dict] = {} 

    # === API dla HTTP ===
    def register_waiter(self, session_id: str) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=1)
        self._http_waiters[session_id] = q

        # ⬅️ NOWE: jeśli przyszła już odpowiedź dla tej sesji, dostarcz ją natychmiast
        pending = self._http_buffer.pop(session_id, None)
        if pending is not None:
            try:
                q.put_nowait(pending)
                self.log(f"[Bridge] delivered buffered reply to waiter for session='{session_id}'")
            except asyncio.QueueFull:
                pass

        return q

    async def send_user_msg(self, conversation_id: str, text: str, session_id: Optional[str] = None):
        sess = session_id or conversation_id
        acl = AclMessage.build_request_user_msg(
            conversation_id=conversation_id,
            text=text,
            ontology="ui",
            session_id=sess,
        )
        await self.send_acl(self._onacl_beh, acl, to_jid=settings.coordinator_jid)
        self.log(f"[Bridge] USER_MSG → Coordinator conv='{conversation_id}' sess='{sess}'")

    # wrzutki z HTTP (opcjonalnie, jeśli korzystasz z kolejki inbox)
    class FromHttp(CyclicBehaviour):
        async def run(self):
            item = await self.agent.inbox.get()
            conv = item["conversation_id"]
            text = item["text"]
            sess = item.get("session_id") or conv
            acl = AclMessage.build_request_user_msg(
                conversation_id=conv, text=text, ontology="ui", session_id=sess
            )
            await self.agent.send_acl(self, acl, to_jid=settings.coordinator_jid)
            self.agent.log(f"[Bridge] USER_MSG from HTTP → Coordinator conv='{conv}'")

    class OnACL(CyclicBehaviour):
        acl_handler_timeout = 0.2

        @acl_handler
        async def run(self, acl: AclMessage, raw_msg):
            if not acl_language_is_json(acl):
                return
            await self.agent.handle_acl(self, raw_msg, acl)

    async def setup(self):
        await super().setup()
        # zachowaj referencję do OnACL, żeby send_user_msg mógł używać self._onacl_beh
        self._onacl_beh = self.OnACL()
        self.add_behaviour(self._onacl_beh)
        self.add_behaviour(self.FromHttp())

    async def handle_acl(self, behaviour, spade_msg, acl: AclMessage):
        payload = acl.payload or {}
        ptype = payload.get("type")

        if ptype in {"PRESENTER_REPLY", "TO_USER"}:
            sess = payload.get("session_id") or acl.conversation_id
            q = self._http_waiters.get(sess)
            if q:
                while not q.empty():
                    with contextlib.suppress(Exception):
                        q.get_nowait()
                await q.put(payload)
                with contextlib.suppress(Exception):
                    del self._http_waiters[sess]
                self.log(f"[Bridge] delivered {ptype} to HTTP waiter for session='{sess}'")
            else:
                # ⬅️ NOWE: brak waitera → zapamiętaj, żeby następny /chat dostał to od ręki
                self._http_buffer[sess] = payload
                self.log(f"[Bridge] buffered {ptype} for session='{sess}' (no waiter)")
                # (opcjonalnie – zostawiasz jak było)
                with contextlib.suppress(Exception):
                    await self.outbox.put(payload)
            return

        self.log(f"[Bridge] UNHANDLED ACL payload={payload}")

