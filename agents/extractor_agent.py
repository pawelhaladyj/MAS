# agents/extractor_agent.py
from __future__ import annotations
import os, json, asyncio, time
from typing import Any, Dict, List

from spade.behaviour import CyclicBehaviour, OneShotBehaviour
from spade.template import Template
from spade.message import Message

from agents.agent import BaseAgent
from agents.protocol.acl_messages import AclMessage, Performative
from agents.common.config import settings

# Tu wpięty Twój ekstraktor LLM; może zwracać pusty wynik na czas MVP
# Oczekiwany zwrot:
# {
#   "extracted": { "budget_total": {"value": 2000, "confidence": 0.92, "raw_span": "2000", "unit":"PLN"} , ... },
#   "missing": ["dates_start", "nights"],
#   "notes": ""
# }
async def llm_extract_slots(session_id: str, context: str, text: str, wanted: List[str]) -> Dict[str, Any]:
    """
    Zwracaj dokładnie:
    {
      "extracted": {slot: {"value": any, "confidence": float, "raw_span": str, "unit": str?}, ...},
      "missing": [slot, ...],
      "notes": str
    }
    """
    try:
        from ai.openai_client import chat_reply  # Twój wrapper
    except Exception:
        # fallback: pusto → Coordinator zapyta o wszystkie wanted
        return {"extracted": {}, "missing": wanted, "notes": "llm disabled"}

    system_prompt = (
        "Jesteś ekstraktorem NLU. Z tekstu użytkownika wydobądź wartości slotów: "
        f"{', '.join(wanted)}. Zwróć WYŁĄCZNIE JSON bez komentarzy.\n"
        "Schema JSON: {\"extracted\": {slot: {\"value\": any, \"confidence\": 0..1, \"raw_span\": str, \"unit\": str?}}, "
        "\"missing\": [slot], \"notes\": str}.\n"
        "Jeśli czegoś nie ma, nie halucynuj — wpisz do \"missing\".\n"
        "Język polski. Krótko. Zero tekstu poza JSON."
    )
    user_prompt = json.dumps({
        "session_id": session_id,
        "context": context or "",
        "message": text or "",
        "wanted": wanted,
    }, ensure_ascii=False)

    try:
        raw = chat_reply(system_prompt=system_prompt, user_text=user_prompt)
    except Exception:
        return {"extracted": {}, "missing": wanted, "notes": "llm error"}

    # twardy parse + sanity-check
    try:
        obj = json.loads(raw)
        extracted = obj.get("extracted") or {}
        # filtrujemy tylko to, o co prosiliśmy
        extracted = {k: v for k, v in extracted.items() if k in wanted and isinstance(v, dict)}
        # normalizacje i domyślne confidence
        for k, meta in list(extracted.items()):
            meta["confidence"] = float(meta.get("confidence") or 0.0)
            if meta["confidence"] < 0 or meta["confidence"] > 1:
                meta["confidence"] = max(0.0, min(1.0, meta["confidence"]))
            meta["raw_span"] = str(meta.get("raw_span") or "")
            # unit opcjonalny
            if "unit" in meta and meta["unit"] is None:
                meta.pop("unit", None)
        missing = [s for s in wanted if s not in extracted]
        notes = obj.get("notes") or ""
        return {"extracted": extracted, "missing": missing, "notes": notes}
    except Exception:
        return {"extracted": {}, "missing": wanted, "notes": "parse error"}


NLU_ONTOLOGY = "nlu"

def _safe_log(agent, msg: str):
    try:
        agent.log(msg)
    except Exception:
        print(msg)

class NluBehaviour(CyclicBehaviour):
    async def on_start(self):
        _safe_log(self.agent, "[Extractor] behaviour started")

    async def run(self):
        msg = await self.receive(timeout=5)
        if not msg:
            return

        try:
            data = json.loads(msg.body or "{}")
            acl = AclMessage.model_validate(data)
        except Exception:
            return

        payload = acl.payload or {}
        if payload.get("type") != "ASK":
            return
        need: List[str] = payload.get("need") or []
        if "EXTRACT" not in [n.upper() for n in need]:
            return

        text = payload.get("text") or ""
        context = payload.get("context") or ""
        session_id = payload.get("session_id") or acl.conversation_id
        wanted = [n for n in need if n.upper() != "EXTRACT"]

        result = await llm_extract_slots(session_id, context, text, wanted)

        # INFORM/FACT, slot nlu.extraction (zgodny z ALLOWED_PERFORMATIVES_BY_TYPE)
        out = AclMessage.build_inform(
            conversation_id=acl.conversation_id,
            payload={"type": "FACT", "slot": "nlu.extraction", "value": result},
            ontology=NLU_ONTOLOGY,
        )
        r = Message(to=str(msg.sender))
        r.thread = acl.conversation_id
        r.set_metadata("performative", "INFORM")
        r.set_metadata("ontology", NLU_ONTOLOGY)
        r.set_metadata("language", "json")
        r.body = out.to_json()
        await self.send(r)
        _safe_log(self.agent, f"[Extractor] INFORM FACT(nlu.extraction) → {msg.sender}")

class AnnounceCapability(OneShotBehaviour):
    def __init__(self, registry_jid: str):
        super().__init__()
        self.registry_jid = registry_jid

    async def run(self):
        conv = f"cap-nlu-{int(time.time())}"
        cap = AclMessage(
            performative=Performative.INFORM,
            conversation_id=conv,
            ontology="system",
            language="json",
            payload={
                "type": "CAPABILITY",
                "provides": [{"ontology": "nlu", "types": ["SLOTS"]}],
                "keys": ["nlu.SLOTS"],
                "agent": os.getenv("EXTRACTOR_AGENT_JID"),
            },
        )
        m = Message(to=self.registry_jid)
        m.thread = conv
        m.set_metadata("performative", "INFORM")
        m.set_metadata("ontology", "system")
        m.set_metadata("language", "json")
        m.body = cap.to_json()
        try:
            await self.send(m)
            _safe_log(self.agent, f"[Extractor] capability announced to {self.registry_jid}")
        except Exception as e:
            _safe_log(self.agent, f"[Extractor] capability announce failed: {e}")
        self.kill()  # OneShotBehaviour: bez await

class ExtractorAgent(BaseAgent):
    async def setup(self):
        # odbiór REQUEST/ASK w ontology=nlu
        t = Template()
        t.set_metadata("performative", "REQUEST")
        t.set_metadata("ontology", NLU_ONTOLOGY)
        self.add_behaviour(NluBehaviour(), t)
        _safe_log(self, "[ExtractorAgent] behaviour registered")

        # ogłoszenie CAPABILITY
        reg = os.getenv("REGISTRY_JID")
        if reg:
            self.add_behaviour(AnnounceCapability(reg))
            _safe_log(self, f"[ExtractorAgent] scheduling capability announce → {reg}")
        else:
            _safe_log(self, "[ExtractorAgent] REGISTRY_JID not set; skipping capability announce")

if __name__ == "__main__":
    jid = os.getenv("EXTRACTOR_AGENT_JID", "user@xmpp.pawelhaladyj.pl")
    pwd = os.getenv("EXTRACTOR_AGENT_PASSWORD", "pass")
    if not jid or not pwd:
        raise SystemExit("EXTRACTOR_AGENT_JID/EXTRACTOR_AGENT_PASSWORD not set")

    async def _main():
        ag = ExtractorAgent(jid, pwd)
        await ag.start(auto_register=True)
        _safe_log(ag, f"[ExtractorAgent] started as {jid}")
        try:
            while True:
                await asyncio.sleep(3600)
        except KeyboardInterrupt:
            pass
        await ag.stop()
    asyncio.run(_main())
