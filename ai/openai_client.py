# ai/openai_client.py
from __future__ import annotations
import os
from typing import Optional

# Spróbuj załadować oficjalnego klienta OpenAI.
# Jeśli go nie ma lub brak klucza, po prostu zwracamy None w czasie wywołania.
try:
    from openai import OpenAI  # >=1.x
except Exception:  # brak biblioteki lub inna wersja
    OpenAI = None  # type: ignore

_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or ""
_OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
_OPENAI_TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.4"))
_OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "180"))

_client = None

def _get_client():
    global _client
    if _client is not None:
        return _client
    if not OpenAI or not _OPENAI_API_KEY:
        return None
    try:
        _client = OpenAI(api_key=_OPENAI_API_KEY)
        return _client
    except Exception:
        return None

def chat_reply(system_prompt: str, user_text: str) -> Optional[str]:
    """
    Wysyła prostą rozmowę system+user do modelu czatowego.
    Zwraca string albo None, gdy klient nie jest dostępny / błąd.
    UWAGA: funkcja synchroniczna (prosto, bez asyncio), wywoływać tylko
    gdy naprawdę chcemy i mamy AI_ENABLED=1.
    """
    client = _get_client()
    if client is None:
        return None
    try:
        # API stylu v1.x
        resp = client.chat.completions.create(
            model=_OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            temperature=_OPENAI_TEMPERATURE,
            max_tokens=_OPENAI_MAX_TOKENS,
        )
        content = resp.choices[0].message.content or ""
        return content.strip()
    except Exception:
        return None
