import os
import asyncio
import json
from collections import deque

from spade.behaviour import OneShotBehaviour, CyclicBehaviour 

from agents.agent import BaseAgent
from agents.common.config import settings
from agents.common.kb import put_fact
from agents.protocol import acl_handler
from agents.protocol.guards import acl_language_is_json
from agents.protocol.acl_messages import AclMessage


class PresenterAgent(BaseAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Pamiętamy klucze ostatnich 64 ramek, by nie obrabiać ich podwójnie
        self._acl_seen_keys = deque(maxlen=64)
    
    
    class Kickoff(OneShotBehaviour):
        async def run(self):
            
            session_id = os.getenv("CONV_ID", "demo-1")
            set_session_state(session_id, "INIT")
            
            # PING w ACL
            acl = AclMessage.build_request(
                conversation_id=os.getenv("CONV_ID", "demo-1"),
                payload={"type": "PING"},
                ontology="default",
            )
            await self.agent.send_acl(self, acl, to_jid=settings.coordinator_jid)
            self.agent.log("sent PING (ACL)")
            
    class OnACL(CyclicBehaviour):
        acl_handler_timeout = 0.2  # ⬅ DODANE: szybka cykliczna próba odbioru
        acl_max_body_bytes = settings.acl_max_body_bytes
        acl_max_idle_ticks = settings.acl_max_idle_ticks  
        
        @acl_handler
        async def run(self, acl: AclMessage, raw_msg):
            # filtr języka, „jak Pan Bóg przykazał”
            if not acl_language_is_json(acl):
                return
            await self.agent.handle_acl(self, raw_msg, acl)
            
    async def setup(self):
        await super().setup()
        self.add_behaviour(self.Kickoff())
        self.add_behaviour(self.OnACL()) 

    async def handle_acl(self, behaviour, spade_msg, acl: AclMessage):
        
        # --- filtr duplikatów (ostatnie 64 ramki) ---
        try:
            k = (
                acl.conversation_id,
                acl.performative.value,
                acl.ontology or "default",
                json.dumps(acl.payload, sort_keys=True, ensure_ascii=False),
            )
        except Exception:
            k = (acl.conversation_id, acl.performative.value, acl.ontology or "default", str(acl.payload))

        if k in self._acl_seen_keys:
            return  # już widzieliśmy tę samą ramkę -> pomijamy
        self._acl_seen_keys.append(k)
        # --- koniec filtra ---
        
        payload = acl.payload or {}
        ptype = payload.get("type")
        
        # ⬇⬇⬇ DODANE: ACK na PING
        if ptype == "PING":
            ack = AclMessage.build_inform_ack(
                conversation_id=acl.conversation_id,
                echo={"type": "PING"},
            )
            await self.send_acl(behaviour, ack, to_jid=str(spade_msg.sender))
            self.log("ACK for PING sent")
            return
        # ⬆⬆⬆ KONIEC wstawki

        if ptype == "ACK":
            self.log(f"ACK: {payload}")
            return

        if ptype == "ASK":
            need = payload["need"][0]
            session_id = payload.get("session_id", os.getenv("CONV_ID", "demo-1"))

            # przejście INIT → GATHER (stan sesji do KB)
            try:
                set_session_state(session_id, "GATHER")
            except Exception as e:
                self.log(f"[warn] failed to set FSM state to GATHER: {e}")

            # Luźna podpowiedź dla człowieka (bez ankiety)
            human_prompt = {
                "budget_total":        "Jaki masz budżet całkowity (PLN)?",
                "dates_start":         "Od kiedy chcesz lecieć (RRRR-MM-DD)?",
                "nights":              "Na ile nocy?",
                "origin_city":         "Z jakiego miasta wylot?",
                "transport_mode":      "Samolot, auto, pociąg?",
                "passport_ok":         "Czy paszport jest ważny (tak/nie)?",
                "destination_pref":    "Preferowana destynacja/region?",
                "weather_min_c":       "Minimalna temp. dzienna (°C)?",
                "party_adults":        "Ilu dorosłych?",
                "party_children_ages": "Wiek dzieci (np. 13,11)?",
                "style":               "Styl (relaks, zwiedzanie, aktywnie)?",
                "hotel_stars_min":     "Min. liczba gwiazdek hotelu?",
                "board":               "Wyżywienie (BB/HB/AI)?",
                "must_haves":          "Warunki konieczne (np. aquapark)?",
                "risk_profile":        "Niski/średni/wysoki? (ryzyka)",
            }.get(need, f"Podaj wartość dla {need}:")
            self.log(f"[Presenter→User] {human_prompt}")

            # TRYB DEMO (opcjonalny): auto-uzupełnianie tylko gdy DEMO_AUTOFILL=1
            if os.getenv("DEMO_AUTOFILL") == "1":
                mock_values = {
                    "budget_total":        "12000",
                    "dates_start":         "2026-02-10",
                    "nights":              "7",
                    "origin_city":         "Lublin",
                    "transport_mode":      "samolot",
                    "passport_ok":         "tak",
                    "destination_pref":    "Egipt",
                    "weather_min_c":       "22",
                    "party_adults":        "2",
                    "party_children_ages": "13,11",
                    "style":               "relaks",
                    "hotel_stars_min":     "5",
                    "board":               "AI",
                    "must_haves":          "aquapark",
                    "risk_profile":        "średni",
                }
                value = mock_values.get(need)
                if value is not None:
                    fact = AclMessage.build_inform_fact(
                        conversation_id=session_id,
                        slot=need,
                        value=value,
                        ontology=acl.ontology or "default",
                    )
                    await self.send_acl(behaviour, fact, to_jid=settings.coordinator_jid)
                    self.log(f"sent FACT (ACL) slot='{need}' value='{value}' (demo)")
            # w trybie normalnym: kończymy na podpowiedzi do człowieka (bez wysyłania FACT)
            return

        if ptype == "USER_MSG":
            text = (payload or {}).get("text", "").strip()
            session_id = payload.get("session_id") or acl.conversation_id

            # opcjonalnie: stan czatu
            try:
                set_session_state(session_id, "CHAT")
            except Exception as e:
                self.log(f"[warn] failed to set FSM state to CHAT: {e}")

            # bardzo prosty „mock AI”: powitaj / dopytaj / potwierdź
            if not text:
                reply_text = "Hej! Opowiedz, dokąd i kiedy chcesz lecieć — ogarniemy resztę 🙂"
            elif "cześć" in text.lower() or "hej" in text.lower():
                reply_text = "Cześć! Masz już jakieś kierunki w głowie czy najpierw pogadamy o budżecie i klimacie?"
            else:
                reply_text = f"Brzmi spoko: „{text}”. Chcesz bardziej chill czy aktywnie? I jaki mniej więcej budżet?"

            reply = AclMessage.build_inform_presenter_reply(
                conversation_id=acl.conversation_id,
                text=reply_text,
                ontology=acl.ontology or "ui",
                session_id=session_id,
            )
            await self.send_acl(behaviour, reply, to_jid=str(spade_msg.sender))
            self.log(f"sent PRESENTER_REPLY: {reply_text}")
            return


        
        if ptype == "OFFER":
            prop = payload.get("proposal", {})
            head = prop.get("headline", "Mam jedną luźną propozycję")
            notes = prop.get("notes", "")
            self.log(f"[Presenter→User] {head} — {notes}")
            return

        if ptype == "CONFIRM":
            slot = payload.get("slot")
            status = payload.get("status")
            self.log(f"CONFIRM: slot='{slot}' status='{status}'")
            return

        self.log(f"OTHER payload: {payload}")
        
def set_session_state(session_id: str, state: str):
    # prosty zapis stanu do KB w kanonicznym slocie
    put_fact(session_id, "session_state", {"value": state})


async def main():
    # prosty healthcheck prezentera
    try:
        put_fact(os.getenv("CONV_ID", "demo-1"), "healthcheck_presenter", {"ok": True})
        print("[Presenter] healthcheck saved to KB")
    except Exception as e:
        print("[Presenter] KB healthcheck FAILED:", e)

    a = PresenterAgent(
        jid=settings.presenter_jid,
        password=settings.presenter_pass,
        verify_security=settings.verify_security,
        # server=settings.xmpp_host,
        # port=settings.xmpp_port,
    )
    await BaseAgent.run_forever(a)


if __name__ == "__main__":
    asyncio.run(main())
