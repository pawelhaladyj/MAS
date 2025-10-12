#!/usr/bin/env python3
from __future__ import annotations
import os
import json
import asyncio
import argparse
import time
from pathlib import Path

from spade.agent import Agent
from spade.behaviour import OneShotBehaviour
from spade.message import Message


# --- Odporny loader .env ---
def _load_env_robust() -> None:
    try:
        from dotenv import load_dotenv  # pip install python-dotenv
    except Exception:
        print("[registry_probe] python-dotenv not installed; skipping .env load")
        return

    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent / ".env",                  # repo root
        Path.cwd() / ".env",                          # bieżący katalog
        here.parent / ".env",                         # scripts/.env
        here.parent.parent / "agents" / ".env",       # agents/.env
    ]
    for p in candidates:
        if p.exists():
            load_dotenv(p)
            print(f"[registry_probe] .env loaded from: {p}")
            return
    print("[registry_probe] .env not found in common locations")


_load_env_robust()
# --- koniec loadera .env ---


class ProbeAgent(Agent):
    class AskBehav(OneShotBehaviour):
        def __init__(self, to_jid: str, conv: str, keys: list[str]):
            super().__init__()
            self.to_jid, self.conv, self.keys = to_jid, conv, keys

        async def run(self):
            body = {
                "performative": "REQUEST",
                "conversation_id": self.conv,
                "ontology": "system",
                "language": "json",
                "payload": {"type": "ASK", "need": ["CAPABILITY"] + list(self.keys)},
            }
            m = Message(to=self.to_jid)
            m.thread = self.conv
            m.set_metadata("performative", "REQUEST")
            m.set_metadata("ontology", "system")
            m.set_metadata("language", "json")
            m.body = json.dumps(body)

            await self.send(m)

            reply = await self.receive(timeout=15)
            if not reply:
                print("[ERR] no reply within timeout")
            else:
                try:
                    data = json.loads(reply.body or "{}")
                    print(json.dumps(data, ensure_ascii=False, indent=2))
                except Exception:
                    print(reply.body)

            await self.agent.stop()

    async def setup(self):
        args = getattr(self, "_args")
        self.add_behaviour(self.AskBehav(args["to"], args["conv"], args["keys"]))


async def _amain(a_to: str, keys: list[str], conv: str, test_jid: str, test_pwd: str):
    print(f"[registry_probe] using test JID: {test_jid}")
    print(f"[registry_probe] probing registry: {a_to}")
    print(f"[registry_probe] keys: {keys}")

    ag = ProbeAgent(test_jid, test_pwd)
    ag._args = {"to": a_to, "conv": conv, "keys": keys}
    await ag.start(auto_register=True)

    # Czekamy aż zachowanie zakończy agent.stop()
    while ag.is_alive():
        await asyncio.sleep(0.2)


def main():
    ap = argparse.ArgumentParser(description="Probe Registry for providers of given capability keys.")
    ap.add_argument("--to", default=os.getenv("REGISTRY_JID"), help="JID rejestru (Registry Agent)")
    ap.add_argument("--keys", nargs="+", default=["weather.WEATHER_ADVICE"], help="Klucze capability do sprawdzenia")
    ap.add_argument("--conv", default=f"registry-probe-{int(time.time())}", help="Conversation ID")
    args = ap.parse_args()

    test_jid = os.getenv("WEATHER_TEST_JID") or os.getenv("REGISTRY_TEST_JID")
    test_pwd = os.getenv("WEATHER_TEST_PASSWORD") or os.getenv("REGISTRY_TEST_PASSWORD")

    if not (test_jid and test_pwd and args.to):
        raise SystemExit("Set WEATHER_TEST_* (or REGISTRY_TEST_*) and REGISTRY_JID in .env")

    asyncio.run(_amain(args.to, args.keys, args.conv, test_jid, test_pwd))


if __name__ == "__main__":
    main()
