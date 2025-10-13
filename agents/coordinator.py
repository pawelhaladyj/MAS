import asyncio
import json
import os
from collections import deque
import time
from typing import Any, Dict, List

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
from spade.behaviour import CyclicBehaviour

# ---- Konfiguracja bez hardkodów (z bezpiecznym fallbackiem) ----
NLU_CAP_KEY   = getattr(settings, "nlu_capability_key", "nlu.SLOTS")
NLU_ONTOLOGY  = getattr(settings, "nlu_ontology", "nlu")
WANTED_SLOTS: List[str] = list(getattr(settings, "nlu_wanted_slots", [
    "budget_total", "dates_start", "nights",
    "origin_city", "destination_pref", "style",
    "weather_min_c", "party_adults", "party_children_ages",
]))
NLU_CONF_MIN  = float(getattr(settings, "nlu_conf_min", os.getenv("NLU_CONF_MIN", "0.7")))


class CoordinatorAgent(BaseAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._acl_seen_keys = deque(maxlen=64)  # pamięć ostatnich kluczy
    
    class OnACL(CyclicBehaviour):
        acl_handler_timeout = getattr(settings, "acl_handler_timeout", 0.2)
        acl_max_body_bytes  = settings.acl_max_body_bytes
        acl_max_idle_ticks  = settings.acl_max_idle_ticks

        @acl_handler
        async def run(self, acl: AclMessage, raw_msg):
            if not acl_language_is_json(acl):
                return
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

        # --- PING → ACK + delikatny COMPOSE:greeting do Presentera ---
        if ptype == "PING":
            ack = AclMessage.build_inform_ack(
                conversation_id=acl.conversation_id,
                echo={"type": "PING"},
            )
            await self.send_acl(behaviour, ack, to_jid=str(spade_msg.sender))
            self.log("acked PING")

            # zamiast hardkodowanego OFFER → poproś Presentera o krótką wiadomość powitalną
            await self._compose(behaviour, acl.conversation_id, payload.get("session_id") or acl.conversation_id, "greeting")
            return

        # --- FACT ---
        if ptype == "FACT":
            sys_slot = payload.get("slot")
            if sys_slot and sys_slot.startswith("capability."):
                self.log(f"ignored system FACT '{sys_slot}'")
                return
            
            slot   = payload.get("slot")
            value  = payload.get("value")
            source = payload.get("source", "user")
            conv_id = acl.conversation_id
            
            # odpowiedź z Extractora
            if slot == "nlu.extraction":
                extraction: Dict[str, Any] = value or {}
                extracted: Dict[str, Any] = (extraction.get("extracted") or {})
                missing: List[str] = list(extraction.get("missing") or [])

                validators = {
                    "budget_total":        validate_budget_total,
                    "dates_start":         validate_dates_start,
                    "nights":              validate_nights, 
                    "passport_ok":         validate_passport_ok, 
                    "party_children_ages": validate_party_children_ages,
                }
                confirmed = []
                for s, meta in extracted.items():
                    try:
                        conf = float(meta.get("confidence") or 0)
                    except Exception:
                        conf = 0.0
                    if s not in CANONICAL_SLOTS or conf < NLU_CONF_MIN:
                        if s not in missing:
                            missing.append(s)
                        continue
                    v = meta.get("value")
                    validator = validators.get(s)
                    if validator:
                        ok, out = validator(v)
                        if not ok:
                            if s not in missing:
                                missing.append(s)
                            continue
                        v = out
                    try:
                        put_fact(conv_id, s, {"value": v, "source": "extractor", "confidence": conf})
                        self.log(f"[NLU] saved to KB: slot='{s}' v='{v}' conf={conf:.2f}")
                        confirmed.append(s)
                    except Exception as e:
                        self.log(f"[NLU] KB write failed for slot='{s}': {e}")

                # potwierdź rozpoznane
                for s in confirmed:
                    confirm = AclMessage.build_inform(
                        conversation_id=conv_id,
                        payload={"type": "CONFIRM", "slot": s, "status": "auto"},
                        ontology=acl.ontology or "default",
                    )
                    await self.send_acl(behaviour, confirm, to_jid=str(spade_msg.sender))

                # poproś o brakujące → do Presentera
                if missing:
                    ask = AclMessage.build_request_ask(
                        conversation_id=conv_id,
                        need=missing,
                        ontology=acl.ontology or "default",
                    )
                    await self.send_acl(behaviour, ask, to_jid=settings.presenter_jid)
                    self.log(f"[NLU] asked for missing: {missing}")

                    # oraz krótka, ludzka dopowiedź od Presentera
                    await self._compose(behaviour, conv_id, payload.get("session_id") or conv_id, "followup")

                # jeśli coś potwierdziliśmy, poproś Presentera o miękki hint
                if confirmed and not missing:
                    await self._compose(behaviour, conv_id, payload.get("session_id") or conv_id, "offer_hint")

                return

            # walidacja slotu
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
            
            # walidacje wartości
            validators = {
                "budget_total":        validate_budget_total,
                "dates_start":         validate_dates_start,
                "nights":              validate_nights, 
                "passport_ok":         validate_passport_ok, 
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
                
                # delikatny hint zamiast sztywnego OFFER
                await self._compose(behaviour, conv_id, payload.get("session_id") or conv_id, "offer_hint")
                return

            except Exception as e:
                self.log(f"ERR KB write FAILED for slot='{slot}': {e}")
            return
        
        # --- USER_MSG ---
        if ptype == "USER_MSG":
            conv_id = acl.conversation_id
            text = (payload or {}).get("text", "")
            session_id = payload.get("session_id") or conv_id

            try:
                put_fact(conv_id, "last_user_msg", {"value": text, "source": "user"})
            except Exception:
                pass

            # 1) natychmiast do Presentera (żeby user dostał odpowiedź)
            forward = AclMessage.build_request_user_msg(
                conversation_id=conv_id,
                text=text,
                ontology="ui",
                session_id=session_id,
            )
            await self.send_acl(behaviour, forward, to_jid=settings.presenter_jid)
            self.log("forwarded USER_MSG to Presenter")

            # 2) równolegle NLU
            context = ""
            extractor_jid = await self._find_provider(behaviour, NLU_CAP_KEY)
            if extractor_jid:
                extraction = await self._ask_extractor(
                    behaviour, extractor_jid, conv_id, session_id, text, context, WANTED_SLOTS
                )
                if extraction:
                    inj = AclMessage.build_inform(
                        conversation_id=conv_id,
                        payload={"type": "FACT", "slot": "nlu.extraction", "value": extraction},
                        ontology=NLU_ONTOLOGY,
                    )
                    await self.handle_acl(behaviour, spade_msg, inj)
            return

        # --- Forward do Bridge (to on gada z API/UIs) ---
        if ptype in {"PRESENTER_REPLY", "TO_USER"}:
            await self.send_acl(behaviour, acl, to_jid=settings.api_bridge_jid)
            self.log(f"routed {ptype} to Bridge")
            return

        # --- METRICS_EXPORT (bez zmian) ---
        if ptype == "METRICS_EXPORT":
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

    # --- Pomocnicze: oddaj niepowiązane wiadomości do głównego pipeline ---
    async def _dispatch_unrelated(self, behaviour, spade_msg):
        try:
            data = json.loads(spade_msg.body or "{}")
            acl2 = AclMessage.model_validate(data)
            await self.handle_acl(behaviour, spade_msg, acl2)
        except Exception:
            pass

    # --- COMPOSE: prosimy Presentera o krótką wypowiedź do użytkownika ---
    async def _compose(self, behaviour, conv_id: str, session_id: str, purpose: str, ontology: str = "ui"):
        # ZAMIANA: zamiast payload.type="COMPOSE", używamy REQUEST/ASK
        compose = AclMessage.build_request(
            conversation_id=conv_id,
            payload={"type": "ASK", "need": ["COMPOSE", purpose], "session_id": session_id},
            ontology=ontology,
        )
        await self.send_acl(behaviour, compose, to_jid=settings.presenter_jid)
        self.log(f"requested COMPOSE({purpose}) from Presenter")


    # --- Registry lookup dla capability (np. nlu.SLOTS) ---
    async def _find_provider(self, behaviour, key: str) -> str | None:
        conv = f"cap-{key.replace('.', '-')}-{int(time.time())}"
        ask = AclMessage.build_request(
            conversation_id=conv,
            payload={"type": "ASK", "need": ["CAPABILITY", key]},
            ontology="system",
        )
        to_registry = getattr(settings, "registry_jid", None) or os.getenv("REGISTRY_JID")
        if not to_registry:
            self.log("[NLU] no REGISTRY_JID configured")
            return None
        await self.send_acl(behaviour, ask, to_jid=to_registry)

        deadline = time.time() + 2.0
        while time.time() < deadline:
            r = await behaviour.receive(timeout=0.25)
            if not r:
                continue
            try:
                data = json.loads(r.body or "{}")
                acl = AclMessage.model_validate(data)
                if acl.conversation_id != conv:
                    await self._dispatch_unrelated(behaviour, r)
                    continue
                p = acl.payload or {}
                if p.get("type") == "FACT" and p.get("slot") == "capability.providers":
                    providers = (p.get("value") or {}).get(key) or []
                    return providers[0] if providers else None
            except Exception:
                await self._dispatch_unrelated(behaviour, r)
                continue
        return None

    # --- Prośba do Extractora i czekanie na odpowiedź ---
    async def _ask_extractor(
        self,
        behaviour,
        extractor_jid: str,
        conv_id: str,
        session_id: str,
        text: str,
        context: str,
        wanted: List[str],
    ) -> Dict[str, Any] | None:
        req = AclMessage.build_request(
            conversation_id=f"{conv_id}-nlu",
            payload={"type": "ASK", "need": ["EXTRACT", *wanted], "text": text, "context": context, "session_id": session_id},
            ontology=NLU_ONTOLOGY,
        )
        await self.send_acl(behaviour, req, to_jid=extractor_jid)

        deadline = time.time() + 3.0
        while time.time() < deadline:
            r = await behaviour.receive(timeout=0.25)
            if not r:
                continue
            try:
                data = json.loads(r.body or "{}")
                acl = AclMessage.model_validate(data)
                if acl.conversation_id != req.conversation_id:
                    await self._dispatch_unrelated(behaviour, r)
                    continue
                p = acl.payload or {}
                if p.get("type") == "FACT" and p.get("slot") == "nlu.extraction":
                    return p.get("value") or {}
            except Exception:
                await self._dispatch_unrelated(behaviour, r)
                continue
        return None


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
