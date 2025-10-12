#!/usr/bin/env python3
# scripts/send_weather_request.py
from __future__ import annotations
"""
Prosty klient testowy XMPP:
- loguje się jako WEATHER_TEST_*,
- wysyła REQUEST {type: WEATHER_ADVICE, place, days} do WeatherAgenta,
- wypisuje INFORM/FAILURE i kończy.
"""

import os
import json
import time
import asyncio
import argparse
from pathlib import Path

from spade.agent import Agent
from spade.behaviour import OneShotBehaviour
from spade.message import Message
from spade.template import Template

# --- .env (odporny load; najpierw agents/.env, później repo-root .env, a na końcu find_dotenv) ---
try:
    from dotenv import load_dotenv, find_dotenv  # pip install python-dotenv
    env_path = None

    # 1) preferuj agents/.env (względem repo)
    cand = [
        Path(__file__).resolve().parents[1] / "agents" / ".env",  # <repo>/agents/.env
        Path(__file__).resolve().parents[1] / ".env",             # <repo>/.env (fallback)
    ]
    for p in cand:
        if p.exists():
            env_path = str(p)
            break

    # 2) jeśli powyższe nie istnieją, spróbuj standardowego find_dotenv (np. gdy odpalasz z innego CWD)
    if not env_path:
        env_path = find_dotenv(filename=".env", usecwd=True)

    # 3) załaduj (nie nadpisuj istniejących ENV)
    if env_path:
        load_dotenv(dotenv_path=env_path, override=False)
except Exception:
    pass

WEATHER_TYPE = "WEATHER_ADVICE"


class ClientAgent(Agent):
    class SendAndWaitBehav(OneShotBehaviour):
        def __init__(self, to_jid: str, place: str, days: int, conv_id: str):
            super().__init__()
            self.to_jid = to_jid
            self.place = place
            self.days = days
            self.conv_id = conv_id

        async def run(self):
            # 1) REQUEST → WEATHER_ADVICE
            payload = {"type": WEATHER_TYPE, "place": self.place, "days": self.days}
            body = {
                "performative": "REQUEST",
                "conversation_id": self.conv_id,
                "ontology": "weather",
                "language": "json",
                "payload": payload,
            }

            msg = Message(to=self.to_jid)
            msg.thread = self.conv_id  # zachowaj rozmowę
            msg.set_metadata("performative", "REQUEST")
            msg.set_metadata("ontology", "weather")
            msg.set_metadata("language", "json")
            msg.body = json.dumps(body)

            await self.send(msg)

            # 2) Czekamy na INFORM/FAILURE (z template)
            tpl = Template()
            tpl.set_metadata("ontology", "weather")
            reply = await self.receive(timeout=20)  # 20 s

            if not reply:
                print("[ERR] Brak odpowiedzi w 20 s.")
                await self.agent.stop()
                return

            try:
                data = json.loads(reply.body or "{}")
            except Exception:
                print("[RAW REPLY]", reply.body)
                await self.agent.stop()
                return

            print("[REPLY performative]", reply.metadata.get("performative"))
            print(json.dumps(data, ensure_ascii=False, indent=2))

            # 3) Koniec pracy agenta-klienta
            await self.agent.stop()

    async def setup(self):
        args = getattr(self, "_args")  # przekazane przez main()
        beh = self.SendAndWaitBehav(args["to"], args["place"], args["days"], args["conv"])
        self.add_behaviour(beh)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Wyślij REQUEST WEATHER_ADVICE do WeatherAgenta")
    p.add_argument("--to", default=os.getenv("WEATHER_AGENT_JID"), help="JID WeatherAgenta (domyślnie z ENV)")
    p.add_argument("--place", required=True, help="Nazwa miejsca (np. 'Praga, CZ')")
    p.add_argument("--days", type=int, default=5, help="Liczba dni prognozy (1..16)")
    p.add_argument("--conv", default=f"weather-demo-{int(time.time())}", help="conversation_id (opcjonalne)")
    return p.parse_args()


async def _amain():
    args = parse_args()

    # Kredencjały testowego klienta (ten skrypt)
    jid = os.getenv("WEATHER_TEST_JID")
    pwd = os.getenv("WEATHER_TEST_PASSWORD")
    if not jid or not pwd:
        raise SystemExit("Ustaw WEATHER_TEST_JID i WEATHER_TEST_PASSWORD w ENV (agents/.env lub .env)")

    if not args.to:
        raise SystemExit("Ustaw WEATHER_AGENT_JID w ENV (agents/.env lub .env) lub podaj --to")

    ag = ClientAgent(jid, pwd)
    ag._args = {"to": args.to, "place": args.place, "days": args.days, "conv": args.conv}

    # W nowych wersjach SPADE start jest korutyną → await
    await ag.start(auto_register=True)

    # Czekamy aż OneShotBehaviour zakończy i agent się zatrzyma
    try:
        while ag.is_alive():
            await asyncio.sleep(0.2)
    finally:
        await ag.stop()


if __name__ == "__main__":
    asyncio.run(_amain())
