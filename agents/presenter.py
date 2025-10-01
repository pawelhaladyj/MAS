from agents.common.kb import put_fact
import os
import asyncio
from spade.agent import Agent
from spade.behaviour import OneShotBehaviour, CyclicBehaviour
from spade.message import Message
from agents.common.config import settings
from agents.protocol.acl_messages import AclMessage, Performative
from agents.protocol.spade_utils import to_spade_message

class PresenterAgent(Agent):
    class Kickoff(OneShotBehaviour):
        async def run(self):
            # 1) Budujemy ACL (bez SPADE Message)
            acl = AclMessage.build_request(
                conversation_id="demo-1",
                payload={"type": "PING"},
                ontology="default",  # opcjonalnie jawnie
            )

            # 2) Dopiero teraz tworzymy SPADE Message z ACL
            msg = to_spade_message(acl, to_jid=settings.coordinator_jid)
            await self.send(msg)
            print("[Presenter] sent PING (ACL)")

    class Inbox(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=10)
            if not msg:
                return

            # Parsowanie ACL z fallbackiem na Pydantic v1
            try:
                try:
                    acl = AclMessage.from_json(msg.body)  # Pydantic v2
                except AttributeError:
                    import json as _json
                    acl = AclMessage(**_json.loads(msg.body))  # Pydantic v1

                try:
                    dump = acl.model_dump()   # v2
                except AttributeError:
                    dump = acl.dict()         # v1

                print("[Presenter] ACL IN:", dump)
            except Exception as e:
                print(f"[Presenter] invalid ACL: {e}; body={msg.body!r}")
                return

            # Od tej chwili używamy wyłącznie payload z ACL:
            payload = acl.payload
            t = payload.get("type")

            if t == "ACK":
                # Potwierdzenie od Koordynatora
                print("[Presenter] ACK:", payload)

            elif t == "ASK":
                # Koordynator prosi o uzupełnienie jednego brakującego slotu
                need = payload["need"][0]
                session_id = payload.get("session_id", os.getenv("CONV_ID", "demo-1"))

                # „Pytanie do człowieka” (na razie tylko log)
                human_prompt = {
                    "budget_total":"Jaki masz budżet całkowity (PLN)?",
                    "dates_start":"Od kiedy chcesz lecieć (RRRR-MM-DD)?",
                    "nights":"Na ile nocy?",
                    "origin_city":"Z jakiego miasta wylot?",
                    "transport_mode":"Samolot, auto, pociąg?",
                    "passport_ok":"Czy paszport jest ważny (tak/nie)?",
                    "destination_pref":"Preferowana destynacja/region?",
                    "weather_min_c":"Minimalna temp. dzienna (°C)?",
                    "party_adults":"Ilu dorosłych?",
                    "party_children_ages":"Wiek dzieci (np. 13,11)?",
                    "style":"Styl (relaks, zwiedzanie, aktywnie)?",
                    "hotel_stars_min":"Min. liczba gwiazdek hotelu?",
                    "board":"Wyżywienie (BB/HB/AI)?",
                    "must_haves":"Warunki konieczne (np. aquapark)?",
                    "risk_profile":"Niski/średni/wysoki? (dot. ryzyk)",
                }.get(need, f"Podaj wartość dla {need}:")
                print(f"[Presenter→User] {human_prompt}")

                # MOCK: automatyczna odpowiedź za użytkownika
                mock_values = {
                    "budget_total":"12000",
                    "dates_start":"2026-02-10",
                    "nights":"7",
                    "origin_city":"Lublin",
                    "transport_mode":"samolot",
                    "passport_ok":"tak",
                    "destination_pref":"Egipt",
                    "weather_min_c":"22",
                    "party_adults":"2",
                    "party_children_ages":"13,11",
                    "style":"relaks",
                    "hotel_stars_min":"5",
                    "board":"AI",
                    "must_haves":"aquapark",
                    "risk_profile":"średni",
                }
                value = mock_values.get(need, "TODO")

                # Odpowiedz FACT do Koordynatora (slot→value) — TERAZ w ACL
                fact_acl = AclMessage.build_inform(
                    conversation_id=session_id,
                    payload={"type": "FACT","slot": need,"value": value,"source": "user"},
                    ontology="default",
                )
                reply = to_spade_message(fact_acl, to_jid=settings.coordinator_jid)
                await self.send(reply)
                print(f"[Presenter] sent FACT (ACL) slot='{need}' value='{value}'")

            elif t == "CONFIRM":
                slot = payload.get("slot")
                status = payload.get("status")
                print(f"[Presenter] CONFIRM: slot='{slot}' status='{status}'")

            else:
                # Inne typy zaloguj z payload
                print("[Presenter] OTHER:", payload)


    async def setup(self):
        print("[Presenter] starting")
        self.add_behaviour(self.Kickoff())
        self.add_behaviour(self.Inbox())

async def main():
    a = PresenterAgent(
        jid=settings.presenter_jid,
        password=settings.presenter_pass,
        verify_security=settings.verify_security,
#        server=settings.xmpp_host,
#        port=settings.xmpp_port, 
    )
    await a.start(auto_register=False)
    print("[Presenter] started")
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    import os, asyncio

    conv_id = os.getenv("CONV_ID", "demo-1")
    try:
        put_fact(conv_id, "healthcheck_presenter", {"ok": True})
        print("[Presenter] healthcheck saved to KB")
    except Exception as e:
        print("[Presenter] KB healthcheck FAILED:", e)

    asyncio.run(main())
