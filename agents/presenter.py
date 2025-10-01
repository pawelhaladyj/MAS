from agents.common.kb import put_fact
import os
import json, asyncio
from spade.agent import Agent
from spade.behaviour import OneShotBehaviour, CyclicBehaviour
from spade.message import Message
from agents.common.config import settings
from agents.protocol.acl_messages import AclMessage, Performative

class PresenterAgent(Agent):
    class Kickoff(OneShotBehaviour):
        async def run(self):
            # Start rozmowy: wyślij PING do Koordynatora
            acl = AclMessage.build_request(
                conversation_id="demo-1",
                payload={"type": "PING"}
            )

            msg = Message(to=settings.coordinator_jid)
            msg.set_metadata("performative", acl.performative.value)
            msg.set_metadata("conversation_id", acl.conversation_id)
            msg.set_metadata("ontology", acl.ontology)  # zostaje "default", ale jawnie
            msg.set_metadata("language", acl.language)  # zostaje "json", ale jawnie
            msg.body = acl.to_json()

            await self.send(msg)
            print("[Presenter] sent PING (ACL)")

    class Inbox(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=10)
            if not msg:
                return

            # Bezpieczne parsowanie JSON
            try:
                data = json.loads(msg.body)
            except Exception as e:
                print(f"[Presenter] bad json: {e}; body={msg.body!r}")
                return

            t = data.get("type")

            if t == "ACK":
                # Potwierdzenie od Koordynatora
                print(f"[Presenter] got:", data)

            elif t == "ASK":
                # Koordynator prosi o uzupełnienie jednego brakującego slotu
                need = data["need"][0]
                session_id = data.get("session_id", os.getenv("CONV_ID", "demo-1"))

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

                # Odpowiedz FACT do Koordynatora (slot→value)
                reply = Message(to=settings.coordinator_jid)
                reply.set_metadata("performative", "INFORM")
                reply.body = json.dumps({
                    "type": "FACT",
                    "session_id": session_id,
                    "slot": need,
                    "value": value,
                    "source": "user",
                })
                await self.send(reply)
                print(f"[Presenter] sent FACT for slot='{need}' value='{value}'")

            else:
                # Inne typy można zalogować
                print(f"[Presenter] got:", data)

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
