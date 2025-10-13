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

from ai.openai_client import chat_reply

from spade.behaviour import CyclicBehaviour

NLU_CAP_KEY = "nlu.SLOTS"
NLU_ONTOLOGY = "nlu"
WANTED_SLOTS: List[str] = [
    "budget_total", "dates_start", "nights",
    "origin_city", "destination_pref", "style",
    "weather_min_c", "party_adults", "party_children_ages",
]
NLU_CONF_MIN = float(os.getenv("NLU_CONF_MIN", "0.7"))


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
            
            # --- NOWE: bezpieczna obsługa odpowiedzi od Extractora ---
            if slot == "nlu.extraction":
                extraction: Dict[str, Any] = value or {}
                extracted: Dict[str, Any] = (extraction.get("extracted") or {})
                missing: List[str] = list(extraction.get("missing") or [])

                # zapisz pewne wartości do KB (po walidacji) + CONFIRM
                validators = {
                    "budget_total": validate_budget_total,
                    "dates_start": validate_dates_start,
                    "nights": validate_nights, 
                    "passport_ok": validate_passport_ok, 
                    "party_children_ages": validate_party_children_ages,
                }
                confirmed = []
                for s, meta in extracted.items():
                    try:
                        conf = float(meta.get("confidence") or 0)
                    except Exception:
                        conf = 0.0
                    if s not in CANONICAL_SLOTS or conf < NLU_CONF_MIN:
                        # jeśli niski confidence albo slot nam nieznany ⇒ poprosimy później
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

                # poproś o brakujące
                if missing:
                    ask = AclMessage.build_request_ask(
                        conversation_id=conv_id,
                        need=missing,
                        ontology=acl.ontology or "default",
                    )
                    await self.send_acl(behaviour, ask, to_jid=str(spade_msg.sender))
                    self.log(f"[NLU] asked for missing: {missing}")

                # (opcjonalnie) od razu wyślij świeżą propozycję
                offer = make_offer(conv_id, acl.ontology or "default")
                await self.send_acl(behaviour, offer, to_jid=str(spade_msg.sender))
                self.log("[NLU] offered update after extraction")
                return
            # --- KONIEC BLOKU 'nlu.extraction' ---

            
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
            session_id = payload.get("session_id") or conv_id

            try:
                put_fact(conv_id, "last_user_msg", {"value": text, "source": "user"})
            except Exception:
                pass

            # ---- NOWE: NLU przez Extractor (koordynator pyta Registry) ----
            context = ""  # MVP: można później zaciągnąć ostatnie fakty z KB i zbudować kontekst
            extractor_jid = await self._find_provider(behaviour, NLU_CAP_KEY)

            if extractor_jid:
                extraction = await self._ask_extractor(
                    behaviour, extractor_jid, conv_id, session_id, text, context, WANTED_SLOTS
                )
                if extraction:
                    # wstrzykuj wynik tak, jakby przyszedł z sieci (ponowne użycie ścieżki FACT/nlu.extraction)
                    inj = AclMessage.build_inform(
                        conversation_id=conv_id,
                        payload={"type": "FACT", "slot": "nlu.extraction", "value": extraction},
                        ontology=NLU_ONTOLOGY,
                    )
                    # ważne: przekazujemy do tej samej kolejki zachowania, by użyć powyższego bloku
                    await self.handle_acl(behaviour, spade_msg, inj)
                    return
            # ---- KONIEC NOWEGO BLOKU NLU ----
            
            # ... po ewentualnym NLU/injection i przed fallbackiem OFFER:
            fwd = AclMessage.build_request_user_msg(
                conversation_id=conv_id,
                text=text,
                ontology=acl.ontology or "ui",
                session_id=session_id,
            )
            await self.send_acl(behaviour, fwd, to_jid=settings.presenter_jid)
            self.log("forwarded USER_MSG to Presenter")
            return

            # Fallback: zachowanie jak dotąd – szybka, luźna propozycja
            offer = make_offer(conv_id, acl.ontology or "default")
            await self.send_acl(behaviour, offer, to_jid=str(spade_msg.sender))
            self.log("sent OFFER in response to USER_MSG")
            return

        # Forward rzeczy "dla użytkownika" do Bridge (to on gada z API)
        if ptype in {"PRESENTER_REPLY", "TO_USER", "OFFER"}:
            await self.send_acl(behaviour, acl, to_jid=settings.api_bridge_jid)
            self.log(f"routed {ptype} to Bridge")
            return
        # ⬆⬆⬆ KONIEC WSTAWKI ⬆⬆⬆

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
        
    async def _dispatch_unrelated(self, behaviour, spade_msg):
        """
        Oddaj ramkę, która przyszła podczas krótkiego oczekiwania w _find_provider/_ask_extractor,
        z powrotem do normalnej ścieżki handle_acl (zachowuje deduplikację).
        """
        try:
            data = json.loads(spade_msg.body or "{}")
            acl2 = AclMessage.model_validate(data)
            await self.handle_acl(behaviour, spade_msg, acl2)
        except Exception:
            # cicho ignoruj śmieci/nie-JSON
            pass

        
    async def _find_provider(self, behaviour, key: str) -> str | None:
        """Zapytaj Registry, kto dostarcza daną capability (np. nlu.SLOTS)."""
        conv = f"cap-{key.replace('.', '-')}-{int(time.time())}"
        ask = AclMessage.build_request(
            conversation_id=conv,
            payload={"type": "ASK", "need": ["CAPABILITY", key]},
            ontology="system",
        )
        
        # wyślij do Registry
        to_registry = getattr(settings, "registry_jid", None) or os.getenv("REGISTRY_JID")
        if not to_registry:
            self.log("[NLU] no REGISTRY_JID configured")
            return None
        await self.send_acl(behaviour, ask, to_jid=to_registry)
        
        # krótko czekamy na INFORM/FACT capability.providers
        deadline = time.time() + 2.0
        while time.time() < deadline:
            r = await behaviour.receive(timeout=0.25)
            if not r:
                continue
            try:
                data = json.loads(r.body or "{}")
                acl = AclMessage.model_validate(data)
                if acl.conversation_id != conv:
                    # ⬅️ NOWE: oddaj do normalnego pipeline
                    await self._dispatch_unrelated(behaviour, r)
                    continue
                p = acl.payload or {}
                if p.get("type") == "FACT" and p.get("slot") == "capability.providers":
                    providers = (p.get("value") or {}).get(key) or []
                    return providers[0] if providers else None
            except Exception:
                # ⬅️ NOWE: też oddaj, jeśli się nie sparsowało/nie pasuje
                await self._dispatch_unrelated(behaviour, r)
                continue
        return None

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
        """Poproś Extractor o ekstrakcję i odbierz FACT(nlu.extraction)."""
        req = AclMessage.build_request(
            conversation_id=f"{conv_id}-nlu",
            payload={"type": "ASK", "need": ["EXTRACT", *wanted], "text": text, "context": context, "session_id": session_id},
            ontology=NLU_ONTOLOGY,
        )
        await self.send_acl(behaviour, req, to_jid=extractor_jid)

        # krótki wait na odpowiedź
        deadline = time.time() + 3.0
        while time.time() < deadline:
            r = await behaviour.receive(timeout=0.25)
            if not r:
                continue
            try:
                data = json.loads(r.body or "{}")
                acl = AclMessage.model_validate(data)
                if acl.conversation_id != req.conversation_id:
                    # ⬅️ NOWE: oddaj do normalnej ścieżki
                    await self._dispatch_unrelated(behaviour, r)
                    continue
                p = acl.payload or {}
                if p.get("type") == "FACT" and p.get("slot") == "nlu.extraction":
                    return p.get("value") or {}
            except Exception:
                # ⬅️ NOWE: też oddaj
                await self._dispatch_unrelated(behaviour, r)
                continue
        return None


        
        
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
                "Jesteś kumplem do rozmowy o wakacjach. "
                "Podaj jedną luźną propozycję otwierającą dialog (po polsku), krótko i bez list.",
                "Zaproponuj jedną luźną propozycję startową do rozmowy o planowanej podróży.",
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
