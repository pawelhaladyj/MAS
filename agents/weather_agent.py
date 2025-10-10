# agents/weather_agent.py
from __future__ import annotations
import os
import json
import asyncio
from typing import Any, Dict

from spade.behaviour import CyclicBehaviour
from spade.template import Template
from spade.message import Message

from agents.agent import BaseAgent  # Twój bazowy agent (logi, KB, itp.)
from agents.protocol import AclMessage, Performative  # Pydanticowy model ACL
from api.owm_client import OWMClient, OWMConfig, summarize_human

WEATHER_TYPE = "WEATHER_ADVICE"

class WeatherAdviceBehav(CyclicBehaviour):
    async def on_start(self):
        self.owm = OWMClient(OWMConfig(api_key=os.environ["OWM_API_KEY"]))
        if hasattr(self.agent, "log"):
            self.agent.log.info("[Weather] behaviour started")

    async def on_end(self):
        await self.owm.aclose()

    async def run(self):
        msg = await self.receive(timeout=10)
        if not msg:
            return

        try:
            body = json.loads(msg.body or "{}")
        except Exception:
            body = {}

        # Spróbuj zmapować do AclMessage (jeśli walidator dopuszcza WEATHER_ADVICE)
        acl: Dict[str, Any]
        try:
            acl_obj = AclMessage.model_validate(body)
            acl = acl_obj.model_dump()
        except Exception:
            # fallback: przyjmij minimalny kontrakt JSON
            acl = body

        payload = (acl.get("payload") or {})
        if payload.get("type") != WEATHER_TYPE:
            # nie nasze – ignoruj (lub przekaż dalej wg. polityki)
            return

        place = payload.get("place") or ""
        days  = int(payload.get("days") or 5)
        lang  = payload.get("lang") or os.getenv("OWM_LANG", "pl")
        units = payload.get("units") or os.getenv("OWM_UNITS", "metric")

        # Geokoder → bierz pierwszy kandydat
        candidates = await self.owm.geocode(place, limit=1)
        if not candidates:
            await self._reply_error(msg, acl, f"Nie znaleziono lokalizacji dla: {place!r}")
            return

        c0 = candidates[0]
        lat, lon = float(c0["lat"]), float(c0["lon"])
        place_name = f'{c0.get("name") or place}' + (f", {c0.get('country')}" if c0.get("country") else "")

        # Prognoza
        fc = await self.owm.forecast_daily(lat, lon, days=days)
        title_and_text, meta = summarize_human(place_name, fc["provider"], fc["data"], days)
        title, text = title_and_text.split("\n", 1) if "\n" in title_and_text else (title_and_text, "")

        # Budujemy INFORM (ACL)
        inform_payload = {
            "type": WEATHER_TYPE,
            "note": {"title": title, "text": text},
            "meta": {
                **meta,
                "lang": lang,
                "units": units,
            },
        }

        try:
            # Preferuj ustandaryzowany AclMessage
            out_acl = AclMessage(
                performative=Performative.INFORM,
                conversation_id=acl.get("conversation_id") or (msg.thread or ""),
                ontology="weather",
                language="json",
                payload=inform_payload,
            )
            body_out = json.dumps(out_acl.model_dump())
        except Exception:
            # fallback – surowy JSON
            body_out = json.dumps({
                "performative": "INFORM",
                "conversation_id": acl.get("conversation_id") or (msg.thread or ""),
                "ontology": "weather",
                "language": "json",
                "payload": inform_payload,
            })

        reply = Message(to=str(msg.sender))
        reply.thread = acl.get("conversation_id") or msg.thread  # zachowaj konwersację
        reply.set_metadata("performative", "INFORM")
        reply.set_metadata("ontology", "weather")
        reply.set_metadata("language", "json")
        reply.body = body_out

        await self.send(reply)
        if hasattr(self.agent, "log"):
            self.agent.log.info(f"[Weather] INFORM sent to {msg.sender} for place={place!r}")

    async def _reply_error(self, msg: Message, acl: Dict[str, Any], err: str):
        payload = {"type": WEATHER_TYPE, "error": err}
        body_out = json.dumps({
            "performative": "FAILURE",
            "conversation_id": acl.get("conversation_id") or (msg.thread or ""),
            "ontology": "weather",
            "language": "json",
            "payload": payload,
        })
        reply = Message(to=str(msg.sender))
        reply.thread = acl.get("conversation_id") or msg.thread
        reply.set_metadata("performative", "FAILURE")
        reply.set_metadata("ontology", "weather")
        reply.set_metadata("language", "json")
        reply.body = body_out
        await self.send(reply)

class WeatherAgent(BaseAgent):
    async def setup(self):
        if hasattr(self, "log"):
            self.log.info("[WeatherAgent] starting")
        beh = WeatherAdviceBehav()
        # FIPA-ACL przez metadane SPADE
        template = Template()
        template.set_metadata("performative", "REQUEST")
        template.set_metadata("ontology", "weather")
        self.add_behaviour(beh, template)
        if hasattr(self, "log"):
            self.log.info("[WeatherAgent] behaviour registered")

if __name__ == "__main__":
    # Klasycznie: konfiguracja z ENV
    jid = os.environ.get("WEATHER_AGENT_JID")
    pwd = os.environ.get("WEATHER_AGENT_PASSWORD")
    if not jid or not pwd:
        raise SystemExit("WEATHER_AGENT_JID/WEATHER_AGENT_PASSWORD nie ustawione")
    agent = WeatherAgent(jid, pwd)
    future = agent.start(auto_register=True)
    future.result()
    try:
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        agent.stop()
