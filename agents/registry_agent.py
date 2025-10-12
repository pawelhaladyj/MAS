# agents/registry_agent.py
from __future__ import annotations
import os
import json
import asyncio
from collections import defaultdict
from typing import Dict, Set, Tuple, List

from spade.behaviour import CyclicBehaviour
from spade.template import Template
from spade.message import Message

from agents.agent import BaseAgent
from agents.protocol import AclMessage, Performative

REGISTRY_ONTOLOGY = "system"

from pathlib import Path

try:
    from dotenv import load_dotenv  # pip install python-dotenv
    _here = Path(__file__).resolve()
    _candidates = [
        _here.parent / ".env",          # agents/.env
        _here.parent.parent / ".env",   # repo root .env (jeśli kiedyś będzie)
        Path.cwd() / ".env",            # bieżący katalog
    ]
    for _p in _candidates:
        if _p.exists():
            load_dotenv(_p)
            print(f"[registry_agent] .env loaded from: {_p}")
            break
    else:
        load_dotenv()  # standardowe zachowanie (zmienne środowiskowe)
except Exception:
    pass
# --- end .env loader ---


def _safe_log(agent, msg: str):
    log = getattr(agent, "log", None)
    if callable(log):
        try:
            log(msg); return
        except Exception:
            pass
    print(msg)


# === BEHAVIOUR: przyjmowanie INFORM/CAPABILITY =================================
class CapabilityIngestBehav(CyclicBehaviour):
    async def run(self):
        msg = await self.receive(timeout=5)
        if not msg:
            return

        try:
            data = json.loads(msg.body or "{}")
            acl = AclMessage.model_validate(data)
        except Exception:
            return

        if acl.performative != Performative.INFORM:
            return
        payload = acl.payload or {}
        if payload.get("type") != "CAPABILITY":
            return

        provides = payload.get("provides") or []
        raw = str(msg.sender or "")
        sender = raw.split("/", 1)[0]  # bare JID
        
        # Oczekujemy listy wpisów: {"ontology": "...", "types": ["...","..."]}
        added: List[str] = []
        for entry in provides:
            ont = (entry.get("ontology") or "default").strip()
            for typ in (entry.get("types") or []):
                t = str(typ).strip()
                if not t:
                    continue
                key = f"{ont}.{t}"
                self.agent.registry[key].add(sender)
                added.append(key)

        if added:
            _safe_log(self.agent, f"[Registry] + {sender} provides {', '.join(sorted(added))}")


# === BEHAVIOUR: odpowiadanie na REQUEST/ASK o capability =======================
class CapabilityQueryBehav(CyclicBehaviour):
    async def run(self):
        msg = await self.receive(timeout=5)
        if not msg:
            return

        try:
            data = json.loads(msg.body or "{}")
            acl = AclMessage.model_validate(data)
        except Exception:
            return

        if acl.performative != Performative.REQUEST:
            return
        payload = acl.payload or {}
        if payload.get("type") != "ASK":
            return

        need = payload.get("need") or []
        wants_cap = any(str(n).strip().upper() == "CAPABILITY" for n in need)
        if not wants_cap:
            return

        # klucze w formacie "ontology.TYPE", np. "weather.WEATHER_ADVICE"
        keys = [s for s in (str(n).strip() for n in need) if "." in s]
        if not keys:
            return

        out: Dict[str, List[str]] = {}
        for k in keys:
            providers = sorted(self.agent.registry.get(k, set()))
            out[k] = providers

        reply_payload = {"type": "FACT", "slot": "capability.providers", "value": out}
        reply_acl = AclMessage.build_inform(
            conversation_id=acl.conversation_id,
            payload=reply_payload,
            ontology=REGISTRY_ONTOLOGY,
        )

        r = Message(to=str(msg.sender))
        r.thread = acl.conversation_id
        r.set_metadata("performative", "INFORM")
        r.set_metadata("ontology", REGISTRY_ONTOLOGY)
        r.set_metadata("language", "json")
        r.body = reply_acl.to_json()
        await self.send(r)


# === AGENT ====================================================================
class RegistryAgent(BaseAgent):
    async def setup(self):
        # Wspólny stan: mapa "ontology.TYPE" -> set(JID)
        self.registry: Dict[str, Set[str]] = defaultdict(set)

        # INFORM/system (CAPABILITY)
        t_inform = Template()
        t_inform.set_metadata("performative", "INFORM")
        t_inform.set_metadata("ontology", REGISTRY_ONTOLOGY)
        self.add_behaviour(CapabilityIngestBehav(), t_inform)

        # REQUEST/system (ASK o capability)
        t_req = Template()
        t_req.set_metadata("performative", "REQUEST")
        t_req.set_metadata("ontology", REGISTRY_ONTOLOGY)
        self.add_behaviour(CapabilityQueryBehav(), t_req)

        _safe_log(self, "[RegistryAgent] behaviours registered")


if __name__ == "__main__":
    jid = os.getenv("REGISTRY_JID")
    pwd = os.getenv("REGISTRY_PASSWORD")
    if not jid or not pwd:
        raise SystemExit("REGISTRY_JID/REGISTRY_PASSWORD not set")

    async def _main():
        ag = RegistryAgent(jid, pwd)
        await ag.start(auto_register=True)
        _safe_log(ag, f"[RegistryAgent] started as {jid}")
        try:
            while True:
                await asyncio.sleep(3600)
        except KeyboardInterrupt:
            pass
        await ag.stop()

    asyncio.run(_main())
