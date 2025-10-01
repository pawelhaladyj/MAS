# agents/protocol/guards.py
def meta_language_is_json(msg) -> bool:
    """
    Zwraca True, jeśli w metadanych SPADE 'language' jest 'json'
    lub jeśli brak nagłówka language (traktujemy jako OK).
    """
    try:
        lang = msg.metadata.get("language") if hasattr(msg, "metadata") else None
    except Exception:
        lang = None
    return (lang is None) or (str(lang).lower() == "json")


def acl_language_is_json(acl) -> bool:
    """
    Zwraca True, jeśli acl.language == 'json' (case-insensitive).
    """
    try:
        return str(acl.language).lower() == "json"
    except Exception:
        return False
