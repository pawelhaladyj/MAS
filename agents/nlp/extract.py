# agents/nlp/extract.py
from __future__ import annotations

import os
import json
import re
from typing import Any, Iterable, List, Tuple, Optional

from agents.common.slots import CANONICAL_SLOTS


def _safe_json_extract(text: str) -> Optional[dict]:
    """
    Przyjmuje surowy tekst od LLM i stara się wydobyć pierwszy poprawny obiekt JSON.
    1) najpierw próbuje json.loads na całości,
    2) jeśli się nie uda, próbuje dopasować największy blok { ... } i sparsować.
    Zwraca dict albo None.
    """
    text = (text or "").strip()
    if not text:
        return None

    # 1) Bezpośrednio
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # 2) Znajdź pierwszy blok JSON { ... }
    # Uwaga: prosty heurystyczny ekstraktor — nie dodajemy tu reguł domenowych
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if m:
        candidate = m.group(0)
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:
            return None
    return None


def _build_system_prompt(allowed_slots: Iterable[str]) -> str:
    """
    Buduje prompt systemowy dla LLM. Zero słowników domenowych, jedynie lista
    kanonicznych slotów jako ograniczenie interfejsu.
    """
    slots_csv = ", ".join(sorted(set(allowed_slots)))
    return (
        "Jesteś ekstraktorem informacji dla asystenta podróży.\n"
        "Twoje zadanie: na podstawie wypowiedzi użytkownika (i ewentualnego kontekstu), "
        "wyodrębnij jawnie podane lub jednoznacznie implikowane fakty i zmapuj je na "
        "kanoniczne sloty asystenta.\n"
        f"Dozwolone sloty (wybierz tylko z tej listy): {slots_csv}\n\n"
        "Zasady:\n"
        "- Nie zgaduj: jeśli coś nie jest jednoznaczne, nie dodawaj faktu.\n"
        "- Zwracaj WYŁĄCZNIE JSON, bez komentarzy i bez tekstu poza JSON.\n"
        "- Schemat odpowiedzi:\n"
        '{ "facts": [ { "slot": "<one-of-allowed>", "value": <any-json-serializable> }, ... ] }\n'
        "- Używaj ISO 8601 dla dat (YYYY-MM-DD), liczby jako liczby, wartości boolean jako true/false.\n"
        "- Jeśli nie ma faktów, zwróć {\"facts\": []}.\n"
    )


def _build_user_payload(text: str, context: Optional[dict]) -> str:
    """
    Pakujemy wejście do czytelnej, jednoznacznej struktury.
    To nie jest ogranicznik — LLM ma pełną swobodę, ale prosimy o jednolity JSON na wyjściu.
    """
    payload = {
        "utterance": text or "",
        "context": context or {},
    }
    return json.dumps(payload, ensure_ascii=False)


def extract_facts_from_text(
    text: str,
    *,
    conversation_context: Optional[dict] = None,
) -> List[Tuple[str, Any]]:
    """
    AI-driven ekstrakcja faktów:
    - Gdy AI_ENABLED=1: woła LLM z prośbą o czysty JSON i mapowanie do kanonicznych slotów.
    - Gdy AI_ENABLED!=1: zwraca pustą listę (nie uprawiamy heurystyk; rozmowa pozostaje luźna).
    Zwraca listę (slot, value).
    """
    if os.getenv("AI_ENABLED", "0") != "1":
        return []

    # Import lokalny, aby nie ładować klienta jeśli AI jest wyłączone.
    try:
        from ai.openai_client import chat_reply  # type: ignore
    except Exception:
        # Jeśli klient nie jest dostępny, nie forsujemy niczego.
        return []

    system_prompt = _build_system_prompt(CANONICAL_SLOTS)
    user_payload = _build_user_payload(text, conversation_context)

    try:
        raw = chat_reply(system_prompt, user_payload)
    except Exception:
        # Jeśli LLM się wywali, trudno — nie zwracamy nic, rozmowa pójdzie dalej luźno.
        return []

    data = _safe_json_extract(raw)
    if not data:
        return []

    facts_out: List[Tuple[str, Any]] = []
    facts = data.get("facts", [])
    if isinstance(facts, list):
        for item in facts:
            if not isinstance(item, dict):
                continue
            slot = item.get("slot")
            value = item.get("value")
            # Szanujemy jedyne ograniczenie interfejsu: slot musi być kanoniczny.
            if isinstance(slot, str) and slot in CANONICAL_SLOTS:
                facts_out.append((slot, value))
    elif isinstance(facts, dict):
        # Na wszelki wypadek akceptujemy też mapę slot->value
        for slot, value in facts.items():
            if isinstance(slot, str) and slot in CANONICAL_SLOTS:
                facts_out.append((slot, value))

    return facts_out
