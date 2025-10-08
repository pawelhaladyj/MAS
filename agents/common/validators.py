# agents/common/validators.py
from __future__ import annotations
from datetime import date

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

