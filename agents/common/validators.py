# agents/common/validators.py
from __future__ import annotations
from datetime import date
import re

def validate_budget_total(v):
    """
    Akceptuje: int/float/str liczbowe. Wymaga wartości > 0.
    Zwraca (ok: bool, normalized_or_msg)
    """
    try:
        if isinstance(v, str):
            v = v.strip().replace(" ", "").replace("_", "")
            if v.endswith("PLN"):
                v = v[:-3]
            v = v.replace(",", ".")
            v = float(v)
        elif isinstance(v, bool):
            return False, "budget_total must be a number"
        v = float(v)
        if v <= 0:
            return False, "budget_total must be > 0"
        # normalizujemy do int PLN (zaokrąglenie w dół)
        return True, int(v)
    except Exception:
        return False, "budget_total must be numeric"

def validate_dates_start(v):
    """
    Akceptuje: 'YYYY-MM-DD'. Nie narzucamy relacji do dzisiejszej daty (brak zależności od czasu testów).
    Zwraca (ok: bool, normalized_or_msg)
    """
    if not isinstance(v, str):
        return False, "dates_start must be string 'YYYY-MM-DD'"
    parts = v.split("-")
    if len(parts) != 3:
        return False, "dates_start must be 'YYYY-MM-DD'"
    y, m, d = parts
    try:
        y, m, d = int(y), int(m), int(d)
        _ = date(y, m, d)  # walidacja poprawności kalendarzowej
        return True, f"{y:04d}-{m:02d}-{d:02d}"
    except Exception:
        return False, "dates_start must be a valid calendar date"
    
def validate_nights(v):
    """
    Akceptuje int/str liczbowe > 0. Normalizuje do int.
    Zwraca (ok: bool, normalized_or_msg)
    """
    try:
        if isinstance(v, str):
            v = v.strip().replace(" ", "").replace("_", "")
        v = int(v)
        if v <= 0:
            return False, "nights must be > 0"
        return True, v
    except Exception:
        return False, "nights must be an integer > 0"

def validate_passport_ok(v):
    """
    Akceptuje: bool lub str ('tak','nie','yes','no','true','false','1','0').
    Zwraca (ok: bool, normalized_or_msg) gdzie normalized to bool.
    """
    if isinstance(v, bool):
        return True, v
    if isinstance(v, (int, float)) and v in (0, 1):
        return True, bool(int(v))
    if isinstance(v, str):
        s = v.strip().lower()
        truthy = {"tak", "yes", "true", "1", "y", "t"}
        falsy  = {"nie", "no", "false", "0", "n", "f"}
        if s in truthy:
            return True, True
        if s in falsy:
            return True, False
    return False, "passport_ok must be boolean (tak/nie)"

def validate_party_children_ages(v):
    """
    Akceptuje:
      - list[int|str] lub str: "13,11" / "13; 11" / "13 11"
    Zasady:
      - każdy wiek to int z przedziału 0..17
      - przynajmniej jeden element
    Zwraca: (ok: bool, normalized_or_msg)
      normalized: list[int] (kolejność zachowana)
    """
    def to_int(x):
        if isinstance(x, bool):
            raise ValueError()
        if isinstance(x, (int, float)):
            return int(x)
        if isinstance(x, str):
            x = x.strip()
            if not x:
                raise ValueError()
            return int(x)
        raise ValueError()

    items = []
    if isinstance(v, str):
        # rozdzielamy po przecinkach/średnikach/spacjach
        raw = [p for p in re.split(r"[,\s;]+", v.strip()) if p]
        try:
            items = [to_int(p) for p in raw]
        except Exception:
            return False, "party_children_ages must be a list of integers"
    elif isinstance(v, (list, tuple)):
        try:
            items = [to_int(p) for p in v]
        except Exception:
            return False, "party_children_ages must be a list of integers"
    else:
        return False, "party_children_ages must be a list or string"

    if not items:
        return False, "party_children_ages cannot be empty"

    for a in items:
        if a < 0 or a > 17:
            return False, "each age must be in range 0..17"

    return True, items


