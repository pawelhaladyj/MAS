# api/owm_client.py
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone
import httpx

@dataclass
class OWMConfig:
    api_key: str
    lang: str = os.getenv("OWM_LANG", "pl")
    units: str = os.getenv("OWM_UNITS", "metric")
    use_forecast16: bool = os.getenv("OWM_USE_FORECAST16", "false").lower() in {"1","true","yes"}
    timeout: float = float(os.getenv("OWM_TIMEOUT", "10"))

class OWMClient:
    def __init__(self, cfg: OWMConfig):
        self.cfg = cfg
        self._http = httpx.AsyncClient(timeout=cfg.timeout)

    async def aclose(self):
        await self._http.aclose()

    async def geocode(self, q: str, limit: int = 1) -> List[Dict[str, Any]]:
        """Direct geocoding → lista kandydatów (name, lat, lon, country, state)."""
        url = "https://api.openweathermap.org/geo/1.0/direct"
        params = {"q": q, "limit": limit, "appid": self.cfg.api_key}
        r = await self._http.get(url, params=params)
        r.raise_for_status()
        return r.json() or []

    async def forecast_daily(self, lat: float, lon: float, days: int = 5) -> Dict[str, Any]:
        """Prognoza dzienna: preferuj Daily 16-day (jeśli dostępna), inaczej One Call 3.0 (do 8 dni)."""
        if self.cfg.use_forecast16:
            # /data/2.5/forecast/daily – do 16 dni
            url = "https://api.openweathermap.org/data/2.5/forecast/daily"
            params = {
                "lat": lat, "lon": lon, "cnt": max(1, min(days, 16)),
                "units": self.cfg.units, "lang": self.cfg.lang, "appid": self.cfg.api_key
            }
            r = await self._http.get(url, params=params)
            r.raise_for_status()
            data = r.json()
            return {"provider": "owm_forecast16", "data": data}
        else:
            # One Call 3.0 – daily do 8 dni
            url = "https://api.openweathermap.org/data/3.0/onecall"
            params = {
                "lat": lat, "lon": lon, "exclude": "minutely,hourly,alerts",
                "units": self.cfg.units, "lang": self.cfg.lang, "appid": self.cfg.api_key
            }
            r = await self._http.get(url, params=params)
            r.raise_for_status()
            data = r.json()
            return {"provider": "owm_onecall3", "data": data}

def _round(x: Optional[float]) -> Optional[int]:
    try:
        return int(round(float(x)))
    except Exception:
        return None

def summarize_human(place_name: str, provider: str, raw: Dict[str, Any], days: int) -> Tuple[str, Dict[str, Any]]:
    """Zwięzła notatka „human-readable” + metadane do KB (fallback regułowy – bez LLM)."""
    lines: List[str] = []
    coords = {"lat": None, "lon": None}
    start = end = None

    if provider == "owm_forecast16":
        city = (raw.get("city") or {})
        coords["lat"] = (city.get("coord") or {}).get("lat")
        coords["lon"] = (city.get("coord") or {}).get("lon")
        seq = (raw.get("list") or [])[:days]
        if seq:
            start = datetime.fromtimestamp(seq[0]["dt"], tz=timezone.utc).date()
            end   = datetime.fromtimestamp(seq[-1]["dt"], tz=timezone.utc).date()
        tmins = [_round((d.get("temp") or {}).get("min")) for d in seq if d.get("temp")]
        tmaxs = [_round((d.get("temp") or {}).get("max")) for d in seq if d.get("temp")]
        pops  = [float(d.get("pop", 0) or 0) for d in seq]
        wet   = sum(1 for p in pops if p >= 0.5)
        desc0 = ((seq[0].get("weather") or [{}])[0]).get("description","") if seq else ""
    else:
        # onecall3
        seq = (raw.get("daily") or [])[:days]
        if seq:
            start = datetime.fromtimestamp(seq[0]["dt"], tz=timezone.utc).date()
            end   = datetime.fromtimestamp(seq[-1]["dt"], tz=timezone.utc).date()
        tmins = [_round((d.get("temp") or {}).get("min")) for d in seq if d.get("temp")]
        tmaxs = [_round((d.get("temp") or {}).get("max")) for d in seq if d.get("temp")]
        pops  = [float(d.get("pop", 0) or 0) for d in seq]
        wet   = sum(1 for p in pops if p >= 0.5)
        desc0 = ((seq[0].get("weather") or [{}])[0]).get("description","") if seq else ""
        # coords nie są w onecall payload – zostawimy None, to i tak info pomocnicze

    if start and end:
        lines.append(f"Zakres: {start} → {end}.")
    if tmins and tmaxs:
        lines.append(f"Temperatury: od ~{min(tmins)}° do ~{max(tmaxs)}°.")
    if wet:
        lines.append(f"Opady możliwe w ~{wet}/{len(seq)} dni (prawd. ≥50%).")
    if desc0:
        lines.append(f"Warunki początkowe: {desc0}.")

    lines.append("Wskazówka: weź warstwy; sprawdź aktualizację dzień wcześniej.")
    text = " ".join(lines) if lines else "Brak danych prognostycznych."

    meta = {
        "coords": coords,
        "provider": provider,
        "days_returned": len(seq),
    }
    title = f"Pogoda: {place_name} ({days} dni)"
    return f"{title}\n{text}", meta
