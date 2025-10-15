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
        self._acl_seen_keys = deque(maxlen=64)
        self._missing_cache: dict[str, tuple[frozenset[str], float]] = {}  # conv_id -> (missing, ts)
        self._cap_cache: dict[str, tuple[str, float]] = {}  # cap_key -> (jid, expires_at)
        self._root_session: dict[str, str] = {}


    
    class OnACL(CyclicBehaviour):
        acl_handler_timeout = getattr(settings, "acl_handler_timeout", 0.2)
        acl_max_body_bytes  = settings.acl_max_body_bytes
        acl_max_idle_ticks  = settings.acl_max_idle_ticks

        @acl_handler
        async def run(self, acl: AclMessage, raw_msg):
            if not acl_language_is_json(acl):
                return
            await self.agent.handle_acl(self, raw_msg, acl)
            
    def _get_session(self, conv_id: str) -> str | None:
        # bezpośrednie trafienie
        sid = self._root_session.get(conv_id)
        if sid:
            return sid
        # jeśli to techniczny conv z sufiksem (np. "-nlu"), spróbuj bazowego
        if conv_id.endswith("-nlu"):
            base = conv_id[:-4]
            return self._root_session.get(base)
        return None

            
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
            # await self._compose(behaviour, acl.conversation_id, payload.get("session_id") or acl.conversation_id, "greeting")
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

                # poproś o brakujące → do Presentera (z deduplikacją)
                if missing:
                    await self._ask_missing(behaviour, conv_id, missing, settings.presenter_jid)
                    # oraz krótka, ludzka dopowiedź od Presentera
                    await self._compose(behaviour, conv_id, "followup")

                # jeśli coś potwierdziliśmy, poproś Presentera o miękki hint
                if confirmed and not missing:
                    await self._compose(behaviour, conv_id, "offer_hint")


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
                await self._compose(behaviour, conv_id, "offer_hint")
                return

            except Exception as e:
                self.log(f"ERR KB write FAILED for slot='{slot}': {e}")
            return
        
        # --- USER_MSG ---
        if ptype == "USER_MSG":
            conv_id = acl.conversation_id
            text = (payload or {}).get("text", "")
            session_id = payload.get("session_id") or conv_id
            # zapamiętaj prawdę o sesji dla głównego conv_id
            if session_id:
                self._root_session[conv_id] = session_id

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


    async def _ask_missing(self, behaviour, conv_id: str, missing: list[str], to_jid: str):
        now = time.time()
        cur = frozenset(missing)
        last = self._missing_cache.get(conv_id)
        # jeśli te same braki w ostatnich 12s → pomiń
        if last and last[0] == cur and (now - last[1]) < 12.0:
            self.log(f"[NLU] missing unchanged, ASK skipped: {sorted(cur)}")
            return
        self._missing_cache[conv_id] = (cur, now)

        sid = self._get_session(conv_id)
        if not sid:
            self.log(f"[NLU] skip ASK missing; no session for conv='{conv_id}'")
            return

        ask = AclMessage.build_request(
            conversation_id=conv_id,
            payload={"type": "ASK", "need": sorted(missing), "session_id": sid},
            ontology="ui",
        )
        await self.send_acl(behaviour, ask, to_jid=to_jid)
        self.log(f"[NLU] asked for missing: {sorted(missing)} (sid='{sid}')")


    # --- Pomocnicze: oddaj niepowiązane wiadomości do głównego pipeline ---
    async def _dispatch_unrelated(self, behaviour, spade_msg):
        try:
            data = json.loads(spade_msg.body or "{}")
            acl2 = AclMessage.model_validate(data)
            await self.handle_acl(behaviour, spade_msg, acl2)
        except Exception:
            pass

    # --- COMPOSE: wyjście do UI zawsze z niezmiennym session_id ---
    async def _compose(self, behaviour, conv_id: str, purpose: str, ontology: str = "ui"):
        sid = self._get_session(conv_id)
        if not sid:
            self.log(f"[UI] no session for conv='{conv_id}', skip COMPOSE({purpose})")
            return
        compose = AclMessage.build_request(
            conversation_id=conv_id,
            payload={"type": "ASK", "need": ["COMPOSE", purpose], "session_id": sid},
            ontology=ontology,
        )
        await self.send_acl(behaviour, compose, to_jid=settings.presenter_jid)
        self.log(f"requested COMPOSE({purpose}) from Presenter (sid='{sid}')")



    # --- Registry lookup dla capability (np. nlu.SLOTS) ---
    async def _find_provider(self, behaviour, key: str) -> str | None:
        now = time.time()

        # 1) Cache hit (pozytywny lub negatywny)
        hit = self._cap_cache.get(key)  # (jid | None, expires_at)
        if hit and hit[1] > now:
            return hit[0] or None

        # 2) Zapytanie do Registry
        conv = f"cap-{key.replace('.', '-')}-{int(now)}"
        ask = AclMessage.build_request(
            conversation_id=conv,
            payload={"type": "ASK", "need": ["CAPABILITY", key]},
            ontology="system",
        )
        to_registry = getattr(settings, "registry_jid", None) or os.getenv("REGISTRY_JID")
        if not to_registry:
            self.log(f"[CAP] no REGISTRY_JID configured for key='{key}'")
            # Fallback: jeśli mamy stary (przeterminowany) hit, użyjemy go
            if hit and hit[0]:
                self.log(f"[CAP] using stale cached provider for {key}: {hit[0]}")
                return hit[0]
            # Specjalny fallback dla NLU
            if key == NLU_CAP_KEY and getattr(settings, "extractor_jid", None):
                return settings.extractor_jid
            return None

        await self.send_acl(behaviour, ask, to_jid=to_registry)

        wait_s   = float(getattr(settings, "cap_cache_wait_s", 2.0))
        deadline = now + wait_s
        provider = None

        while time.time() < deadline:
            r = await behaviour.receive(timeout=0.25)
            if not r:
                continue
            try:
                data = json.loads(r.body or "{}")
                acl2 = AclMessage.model_validate(data)
                if acl2.conversation_id != conv:
                    # oddaj niepowiązane wiadomości do głównego pipeline
                    await self._dispatch_unrelated(behaviour, r)
                    continue
                p = acl2.payload or {}
                if p.get("type") == "FACT" and p.get("slot") == "capability.providers":
                    providers = (p.get("value") or {}).get(key) or []
                    provider = providers[0] if providers else None
                    break
            except Exception:
                await self._dispatch_unrelated(behaviour, r)
                continue

        # 3) Aktualizacja cache (pozytywny/negatywny)
        ttl     = float(getattr(settings, "cap_cache_ttl", 300.0))   # np. 5 min
        neg_ttl = float(getattr(settings, "cap_neg_cache_ttl", 10.0))  # krótki backoff
        expires = time.time() + (ttl if provider else neg_ttl)
        self._cap_cache[key] = (provider, expires)

        if provider:
            self.log(f"[CAP] {key} -> {provider} (cached {int(ttl)}s)")
            return provider

        # 4) Fallbacki, jeśli nie udało się zdobyć providera
        if hit and hit[0]:
            self.log(f"[CAP] using stale cached provider for {key}: {hit[0]}")
            return hit[0]

        if key == NLU_CAP_KEY and getattr(settings, "extractor_jid", None):
            self.log(f"[CAP] fallback to static extractor_jid for {key}")
            return settings.extractor_jid

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
        # --- ustal bazową sesję dla wątku (niezmienną w całym dialogu) ---
        # jeśli nie ma mapy, załóż ją
        if not hasattr(self, "_root_session"):
            self._root_session: Dict[str, str] = {}

        base_sess = self._root_session.get(conv_id) or session_id
        nlu_conv  = f"{conv_id}-nlu"

        # zmapuj techniczny conv '-nlu' na tę samą, bazową sesję
        self._root_session[nlu_conv] = base_sess

        # --- wyślij prośbę do Extractora dla technicznego conv_id ---
        req = AclMessage.build_request(
            conversation_id=nlu_conv,
            payload={
                "type": "ASK",
                "need": ["EXTRACT", *wanted],
                "text": text,
                "context": context,
                # Krytyczne: nie propagujemy żadnych pochodnych; zawsze bazowy session_id
                "session_id": base_sess,
            },
            ontology=NLU_ONTOLOGY,
        )
        await self.send_acl(behaviour, req, to_jid=extractor_jid)

        # --- poczekaj na odpowiedź tylko dla tego conv_id ---
        deadline = time.time() + 3.0
        while time.time() < deadline:
            r = await behaviour.receive(timeout=0.25)
            if not r:
                continue
            try:
                data = json.loads(r.body or "{}")
                acl2 = AclMessage.model_validate(data)
                if acl2.conversation_id != nlu_conv:
                    # wszystko inne oddaj normalnemu pipeline
                    await self._dispatch_unrelated(behaviour, r)
                    continue
                p = acl2.payload or {}
                if p.get("type") == "FACT" and p.get("slot") == "nlu.extraction":
                    return p.get("value") or {}
            except Exception:
                await self._dispatch_unrelated(behaviour, r)
                continue
        return None
        

if __name__ == "__main__":
    asyncio.run(main())
