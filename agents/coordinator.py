import asyncio
import json
import os
from collections import deque

from agents.agent import BaseAgent
from agents.common.kb import put_fact
from agents.common.config import settings
from agents.protocol.acl_messages import AclMessage
from agents.protocol import acl_handler
from agents.protocol.guards import acl_language_is_json
from agents.common.slots import CANONICAL_SLOTS
from agents.common.validators import (
    validate_budget_total, validate_dates_start, validate_nights,
    validate_passport_ok, validate_party_children_ages
)

from ai.openai_client import chat_reply

from spade.behaviour import CyclicBehaviour


class CoordinatorAgent(BaseAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._acl_seen_keys = deque(maxlen=64)  # pamięć ostatnich kluczy
    
    class OnACL(CyclicBehaviour):
        acl_handler_timeout = 0.2  # szybki „tick” odbioru
        acl_max_body_bytes = settings.acl_max_body_bytes      # ⬅ NOWE
        acl_max_idle_ticks = settings.acl_max_idle_ticks

        @acl_handler
        async def run(self, acl: AclMessage, raw_msg):
            if not acl_language_is_json(acl):
                return
            # delegacja do istniejącej logiki
            await self.agent.handle_acl(self, raw_msg, acl)
            
    async def setup(self):
        await super().setup()
        self.add_behaviour(self.OnACL())
    
    async def handle_acl(self, behaviour, spade_msg, acl: AclMessage):
        # --- filtr duplikatów (ostatnie 64 ramki) ---
        try:
            key = (
                acl.conversation_id,
                acl.performative.value,
                acl.ontology or "default",
                json.dumps(acl.payload, sort_keys=True, ensure_ascii=False),
            )
        except Exception:
            key = (acl.conversation_id, acl.performative.value, acl.ontology or "default", str(acl.payload))

        if key in self._acl_seen_keys:
            return
        self._acl_seen_keys.append(key)
        # --- koniec filtra ---
        
        payload = acl.payload or {}
        ptype = payload.get("type")

        if ptype == "PING":
            # ACK (builder)
            ack = AclMessage.build_inform_ack(
                conversation_id=acl.conversation_id,
                echo={"type": "PING"},
            )
            await self.send_acl(behaviour, ack, to_jid=str(spade_msg.sender))
            self.log("acked PING")

            # NOWE: startowa, luźna propozycja zamiast ASK
            offer = make_offer(acl.conversation_id, acl.ontology or "default")
            await self.send_acl(behaviour, offer, to_jid=str(spade_msg.sender))
            self.log("sent initial OFFER")
            return

        if ptype == "FACT":
            slot = payload.get("slot")
            value = payload.get("value")
            source = payload.get("source", "user")
            conv_id = acl.conversation_id
            
            # ⬇⬇⬇ DODANE: walidacja slota
            if slot not in CANONICAL_SLOTS:
                fail = AclMessage.build_failure(
                    conversation_id=conv_id,
                    code="VALIDATION_ERROR",
                    message=f"Unknown slot '{slot}'",
                    details={"allowed": sorted(CANONICAL_SLOTS)},
                )
                await self.send_acl(behaviour, fail, to_jid=str(spade_msg.sender))
                self.log(f"rejected FACT for unknown slot='{slot}'")
                return
            # ⬆⬆⬆ KONIEC wstawki
            
                        # --- walidacje wartości dla wybranych slotów ---
            validators = {
                "budget_total": validate_budget_total,
                "dates_start": validate_dates_start,
                "nights": validate_nights, 
                "passport_ok": validate_passport_ok, 
                "party_children_ages": validate_party_children_ages,
            }
            validator = validators.get(slot)
            if validator:
                ok, out = validator(value)
                if not ok:
                    fail = AclMessage.build_failure(
                        conversation_id=conv_id,
                        code="VALIDATION_ERROR",
                        message=f"Invalid value for '{slot}'",
                        details={"reason": out},
                    )
                    await self.send_acl(behaviour, fail, to_jid=str(spade_msg.sender))
                    self.log(f"rejected FACT slot='{slot}' reason='{out}'")
                    return
                # normalizacja wartości (np. int dla budget_total, sformatowana data)
                value = out

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
                
                # ⬇ NOWE: lekka propozycja na bazie nowych faktów (bez dopytywania)
                offer = make_offer(conv_id, acl.ontology or "default")
                await self.send_acl(behaviour, offer, to_jid=str(spade_msg.sender))
                self.log("offered update based on user prefs")
                return

            except Exception as e:
                self.log(f"ERR KB write FAILED for slot='{slot}': {e}")
            return
        
        if ptype == "USER_MSG":
            conv_id = acl.conversation_id
            text = (payload or {}).get("text", "")

            # (opcjonalnie) zapisz ostatnią wypowiedź usera do KB
            try:
                put_fact(conv_id, "last_user_msg", {"value": text, "source": "user"})
            except Exception:
                pass

            # wygeneruj luźną propozycję (AI jeśli AI_ENABLED=1, inaczej stub)
            offer = self._make_offer(conv_id, acl.ontology or "default")
            # odeślij do nadawcy (API bridge), który może przekazać to dalej do klienta
            await self.send_acl(behaviour, offer, to_jid=str(spade_msg.sender))
            self.log("sent OFFER in response to USER_MSG")
            return

        
        if ptype == "METRICS_EXPORT":
            # Zrzut liczników do KB i potwierdzenie
            try:
                slot = self.export_metrics(session_id="system", slot_prefix="metrics")
                confirm = AclMessage.build_inform(
                    conversation_id=acl.conversation_id,
                    payload={"type": "CONFIRM", "slot": "metrics_export", "status": slot or "failed"},
                    ontology=acl.ontology or "default",
                )
                await self.send_acl(behaviour, confirm, to_jid=str(spade_msg.sender))
                self.log(f"metrics exported to KB slot='{slot}'")
            except Exception as e:
                fail = AclMessage.build_failure(
                    conversation_id=acl.conversation_id,
                    code="INTERNAL_ERROR",
                    message="Metrics export failed",
                    details={"error": str(e)},
                )
                await self.send_acl(behaviour, fail, to_jid=str(spade_msg.sender))
                self.log(f"metrics export FAILED: {e}")
            return


        # Inne typy — dyscyplina: tylko log.
        self.log(f"OTHER payload: {payload}")
        
def make_offer(conversation_id: str, ontology: str) -> AclMessage:
    """Lekka, wstępna propozycja: AI (gdy AI_ENABLED=1) lub bezpieczny fallback."""
    proposal = {
        "headline": "Na start: Egipt na tydzień all-inclusive?",
        "notes": "Luźna podpowiedź — możemy iść w inną stronę, jeśli wolisz.",
        "details": {
            "destination": "Hurghada (Egipt)",
            "duration_nights": 7,
            "board": "AI",
            "stars": 5,
        },
    }

    if os.getenv("AI_ENABLED", "0") == "1":
        try:
            import ai.openai_client as ai_mod
            ai_text = ai_mod.chat_reply(
                system_prompt=(
                    "Jesteś kumplem do rozmowy o wakacjach. "
                    "Podaj jedną luźną propozycję otwierającą dialog (po polsku), krótko i bez list."
                ),
                user_text="Zaproponuj jedną luźną propozycję startową do rozmowy o planowanej podróży.",
            )
            if ai_text:
                first_line = ai_text.strip().splitlines()[0][:120]
                proposal["headline"] = first_line or proposal["headline"]
                proposal["notes"] = ai_text.strip() or proposal["notes"]
        except Exception:
            # cichy fallback – zostaje propozycja domyślna
            pass

    return AclMessage.build_inform(
        conversation_id=conversation_id,
        payload={"type": "OFFER", "proposal": proposal},
        ontology=ontology,
    )

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
