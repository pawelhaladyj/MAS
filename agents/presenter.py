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

from ai.openai_client import chat_reply  # opcjonalny wrapper (bezpieczny)


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
            needs = payload.get("need") or []
            session_id = payload.get("session_id", os.getenv("CONV_ID", "demo-1"))

            # heurystyka: jeśli 1 slot → krótki prompt, jeśli wiele → lista pytań
            if len(needs) == 1:
                human_prompt = prompt_for_slot(needs[0])
            else:
                human_prompt = "Dopytam, żeby lepiej trafić:\n" + "\n".join(f"• {prompt_for_slot(s)}" for s in needs)

            self.log(f"[Presenter→User] {human_prompt}")

            reply = AclMessage.build_inform_presenter_reply(
                conversation_id=acl.conversation_id,
                text=human_prompt,
                ontology=acl.ontology or "ui",
                session_id=session_id,
            )
            await self.send_acl(behaviour, reply, to_jid=str(spade_msg.sender))
            self.log("sent PRESENTER_REPLY (ASK→prompt)")
            return
        
        if ptype == "COMPOSE":
            purpose = (payload.get("purpose") or "offer_hint").lower()
            session_id = payload.get("session_id") or acl.conversation_id

            # Spróbuj AI jeśli włączone w settings; fallback na krótkie teksty
            ai_enabled = getattr(settings, "presenter_ai_enabled", os.getenv("AI_ENABLED", "0") == "1")
            text = None

            if ai_enabled:
                system = (
                    "Jesteś kumplem-doradcą podróży: krótko, po polsku, bez list wypunktowanych, "
                    "jedna wiadomość. Dopytuj naturalnie krok po kroku."
                )
                user = f"Cel: {purpose}. Odpowiedz zwięźle w 1–2 zdaniach."
                maybe = chat_reply(system, user)
                if maybe:
                    text = maybe.strip()

            if not text:
                if purpose == "greeting":
                    text = getattr(
                        settings,
                        "presenter_greeting_text",
                        "Hej! Opowiedz, dokąd i kiedy chcesz jechać — ogarniemy resztę 🙂",
                    )
                elif purpose in ("offer_hint", "followup"):
                    text = "Dopytam tylko o kilka rzeczy (budżet, daty i miasto startu), żeby dobrze trafić z propozycją."
                else:
                    text = "Jasne! Napisz proszę budżet, termin i skąd ruszasz — pomogę doprecyzować."

            reply = AclMessage.build_inform_presenter_reply(
                conversation_id=acl.conversation_id,
                text=text,
                ontology=acl.ontology or "ui",
                session_id=session_id,
            )
            await self.send_acl(behaviour, reply, to_jid=str(spade_msg.sender))
            self.log(f"sent PRESENTER_REPLY (COMPOSE→text): {text}")
            return

        if ptype == "USER_MSG":
            text = (payload or {}).get("text", "").strip()
            session_id = payload.get("session_id") or acl.conversation_id

            # opcjonalnie: stan czatu
            try:
                set_session_state(session_id, "CHAT")
            except Exception as e:
                self.log(f"[warn] failed to set FSM state to CHAT: {e}")

            # Spróbuj AI jeśli włączone w settings; brak twardych ENV
            reply_text = None
            ai_enabled = getattr(settings, "presenter_ai_enabled", os.getenv("AI_ENABLED", "0") == "1")
            if ai_enabled and text:
                system = (
                    "Jesteś kumplem-doradcą podróży: luz, życzliwość, bez ankiety. "
                    "Dopytuj tylko naturalnie, krok po kroku. Odpowiadaj po polsku, krótko."
                )
                maybe = chat_reply(system, text)
                if maybe:
                    reply_text = maybe

            # Fallback – krótkie, konfigurowalne
            if not reply_text:
                if not text:
                    reply_text = getattr(
                        settings,
                        "presenter_greeting_text",
                        "Hej! Opowiedz, dokąd i kiedy chcesz jechać — ogarniemy resztę 🙂",
                    )
                elif "cześć" in text.lower() or "hej" in text.lower():
                    reply_text = "Cześć! Wolisz najpierw kierunek czy ustalimy budżet i klimat wyjazdu?"
                else:
                    reply_text = "Brzmi spoko! Wolisz raczej chill czy aktywnie? I jaki mniej więcej budżet?"


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
            proposal = payload.get("proposal") or {}
            head = proposal.get("headline") or getattr(
                settings, "presenter_default_offer_headline", "Mam jedną propozycję na start"
            )
            notes = proposal.get("notes") or getattr(
                settings, "presenter_default_offer_notes", "Luźna podpowiedź — możemy iść w inną stronę, jeśli wolisz."
            )
            text = f"{head}. {notes}".strip()
            reply = AclMessage.build_inform_presenter_reply(
                conversation_id=acl.conversation_id,
                text=text,
                ontology=acl.ontology or "ui",
                session_id=payload.get("session_id") or acl.conversation_id,
            )
            await self.send_acl(behaviour, reply, to_jid=str(spade_msg.sender))
            self.log(f"sent PRESENTER_REPLY (OFFER→text): {text}")
            return

        
def set_session_state(session_id: str, state: str):
    # prosty zapis stanu do KB w kanonicznym slocie
    put_fact(session_id, "session_state", {"value": state})

def prompt_for_slot(slot: str) -> str:
    labels = {
        "budget_total":        "Jaki masz budżet całkowity (PLN)?",
        "dates_start":         "Od kiedy chcesz wyruszyć (RRRR-MM-DD)?",
        "nights":              "Na ile nocy?",
        "origin_city":         "Z jakiego miasta start?",
        "destination_pref":    "Preferowana destynacja/region?",
        "style":               "Styl (relaks, zwiedzanie, aktywnie)?",
        "weather_min_c":       "Minimalna temp. dzienna (°C)?",
        "party_adults":        "Ilu dorosłych?",
        "party_children_ages": "Wiek dzieci (np. 13,11)?",
        # resztę możesz dopisywać bez zmiany logiki
    }
    return labels.get(slot, f"Podaj wartość dla: {slot}")

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
