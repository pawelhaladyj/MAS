# agents/api_bridge.py
from __future__ import annotations

import json
from typing import Optional

from agents.agent import BaseAgent
from agents.common.config import settings
from agents.common.telemetry import log_acl_event
from agents.protocol.acl_messages import AclMessage
from agents.protocol.spade_utils import to_spade_message
from agents.protocol.guards import acl_language_is_json

from spade.behaviour import CyclicBehaviour


class ApiBridgeAgent(BaseAgent):
    """
    Minimalny mostek XMPP ↔ API.
    - Uruchamiany przez FastAPI (lifespan) gdy API_BRIDGE_ENABLED=1.
    - Czyta wpisy z asyncio.Queue (inbox) i forwarduje do Presentera.
    - Odkłada odpowiedzi od agentów (np. PRESENTER_REPLY) do asyncio.Queue (outbox).
    """

    def __init__(self, *args, inbox, outbox, **kwargs):
        super().__init__(*args, **kwargs)
        self._inbox = inbox                      # asyncio.Queue → przychodzi z API
        self._outbox = outbox                    # asyncio.Queue → wraca do API
        self.default_target_jid = settings.presenter_jid

    class Inbox(BaseAgent.Inbox):
        """Standardowy odbiornik ACL (gdyby ktoś pisał do mostka po XMPP)."""
        pass

    class BridgePump(CyclicBehaviour):
        """Pompa: czyta z kolejki HTTP → buduje ACL → wysyła do Presentera."""
        async def run(self):
            item = None
            try:
                item = await self.agent._inbox.get()
            except Exception:
                return
            if not item:
                return

            text: str = item.get("text", "")
            conv: str = item.get("conversation_id") or "demo-1"
            sess: str = item.get("session_id") or conv
            to_jid: str = item.get("to_jid") or self.agent.default_target_jid
            ontology: str = item.get("ontology") or "ui"

            acl = AclMessage.build_request_user_msg(
                conversation_id=conv,
                text=text,
                ontology=ontology,
                session_id=sess,
            )

            try:
                log_acl_event(acl.conversation_id, "OUT", json.loads(acl.to_json()))
            except Exception as e:
                self.agent.log(f"[telemetry] OUT failed: {e}")

            msg = to_spade_message(acl, to_jid=to_jid)
            await self.send(msg)
            self.agent.log(f"ACL OUT to={to_jid} payload={acl.payload}")

    async def setup(self):
        self.add_behaviour(self.Inbox())
        self.add_behaviour(self.BridgePump())
        self.log("starting")

    async def handle_acl(self, behaviour, spade_msg, acl: AclMessage):
        payload = acl.payload or {}
        ptype = payload.get("type")

        if not acl_language_is_json(acl):
            return

        if ptype == "PING":
            ack = AclMessage.build_inform_ack(
                conversation_id=acl.conversation_id,
                echo={"type": "PING"},
            )
            await self.send_acl(behaviour, ack, to_jid=str(spade_msg.sender))
            self.log("acked PING")
            return

        if ptype == "ACK":
            self.log(f"ACK: {payload}")
            return

        if ptype == "PRESENTER_REPLY":
            # Przekaż odpowiedź do API przez outbox
            try:
                await self._outbox.put({
                    "conversation_id": acl.conversation_id,
                    "payload": payload,
                })
                self.log(f"delivered PRESENTER_REPLY to API outbox: {payload}")
            except Exception as e:
                self.log(f"[bridge] failed to put reply into outbox: {e}")
            return

        if ptype == "USER_MSG":
            txt = payload.get("text", "")
            sess = payload.get("session_id")
            self.log(f"[BRIDGE] USER_MSG via XMPP: {txt!r} (session={sess})")
            return

        self.log(f"OTHER payload: {payload}")
