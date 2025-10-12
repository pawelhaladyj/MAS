# agents/weather_agent.py
from __future__ import annotations
import os
import json
import asyncio
from typing import Any, Dict
import time

from spade.behaviour import CyclicBehaviour, OneShotBehaviour
from spade.template import Template
from spade.message import Message

from agents.agent import BaseAgent  # Twój bazowy agent (logi, KB, itp.)
from agents.protocol import AclMessage, Performative  # Pydanticowy model ACL
from api.owm_client import OWMClient, OWMConfig, summarize_human
from agents.protocol.acl_messages import AclMessage, Performative

from agents.protocol import AclMessage
from agents.protocol.spade_utils import to_spade_message  # już jest w repo

from dotenv import load_dotenv  # pip install python-dotenv

load_dotenv()
    
WEATHER_TYPE = "WEATHER_ADVICE"

def _safe_log(target, msg: str):
    """
    Delikatny logger: jeśli target.log jest funkcją → wywołaj,
    jeśli ma .info → użyj, w przeciwnym razie print.
    """
    log = getattr(target, "log", None)
    if callable(log):
        try:
            log(msg)
            return
        except Exception:
            pass
    if hasattr(log, "info"):
        try:
            log.info(msg)
            return
        except Exception:
            pass
    print(msg)


class WeatherAdviceBehav(CyclicBehaviour):
    async def on_start(self):
        self.owm = OWMClient(OWMConfig(api_key=os.environ["OWM_API_KEY"]))
        if hasattr(self.agent, "log"):
            _safe_log(self.agent, "[Weather] behaviour started")
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
        # agents/weather_agent.py  (wewnątrz async def run, tuż przed: title_and_text = ...)
        try:
            fc = await self.owm.forecast_daily(lat, lon, days=days)
        except Exception as e:
            await self._reply_error(msg, acl, f"OpenWeather błąd: {e}")
            return
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
            _safe_log(self.agent, f"[Weather] INFORM sent to {msg.sender} for place={place!r}")

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

class AnnounceCapabilityBehav(OneShotBehaviour):
    def __init__(self, registry_jid: str):
        super().__init__()
        self.registry_jid = registry_jid

    async def run(self):
        conv = f"cap-weather-{int(time.time())}"
        acl = AclMessage(
            performative=Performative.INFORM,
            conversation_id=conv,
            ontology="system",
            language="json",
            payload={
                "type": "CAPABILITY",
                "provides": [{"ontology": "weather", "types": ["WEATHER_ADVICE"]}],
                "keys": ["weather.WEATHER_ADVICE"],
                "agent": os.getenv("WEATHER_AGENT_JID"),
            },
        )
        m = Message(to=self.registry_jid)
        m.thread = conv
        m.set_metadata("performative", "INFORM")
        m.set_metadata("ontology", "system")
        m.set_metadata("language", "json")
        m.body = acl.to_json()

        try:
            await self.send(m)
            _safe_log(self.agent, f"[WeatherAgent] capability announced to {self.registry_jid}")
        except Exception as e:
            _safe_log(self.agent, f"[WeatherAgent] capability announce failed: {e}")

        # ⬇⬇⬇ TUTAJ BEZ await
        self.kill()


class WeatherAgent(BaseAgent):
    async def setup(self):
        _safe_log(self, "[WeatherAgent] starting")

        # rejestrujemy główne zachowanie pogodowe
        beh = WeatherAdviceBehav()
        tpl = Template()
        tpl.set_metadata("performative", "REQUEST")
        tpl.set_metadata("ontology", "weather")
        self.add_behaviour(beh, tpl)
        _safe_log(self, "[WeatherAgent] behaviour registered")

        # planujemy ogłoszenie capability jako OneShotBehaviour
        reg_jid = os.getenv("REGISTRY_JID")
        if reg_jid:
            self.add_behaviour(AnnounceCapabilityBehav(reg_jid))
            _safe_log(self, f"[WeatherAgent] scheduling capability announce → {reg_jid}")
        else:
            _safe_log(self, "[WeatherAgent] REGISTRY_JID not set; skipping capability announce")


if __name__ == "__main__":
    # (opcjonalnie) autoload .env
    try:
        from dotenv import load_dotenv  # pip install python-dotenv
        load_dotenv()
    except Exception:
        pass

    jid = os.getenv("WEATHER_AGENT_JID")
    pwd = os.getenv("WEATHER_AGENT_PASSWORD")
    if not jid or not pwd:
        raise SystemExit("WEATHER_AGENT_JID/WEATHER_AGENT_PASSWORD nie ustawione")

    async def _amain():
        agent = WeatherAgent(jid, pwd)
        # WAŻNE: w nowych SPADE to korutyna → trzeba await
        await agent.start(auto_register=True)
        if hasattr(agent, "log"):
            _safe_log(agent, f"[WeatherAgent] started as {jid}")
        try:
            while True:
                await asyncio.sleep(3600)
        except KeyboardInterrupt:
            pass
        await agent.stop()

    asyncio.run(_amain())

