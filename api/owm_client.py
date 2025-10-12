# api/owm_client.py
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone, date
from collections import Counter
from itertools import islice
import httpx

@dataclass
class OWMConfig:
    api_key: str
    lang: str = os.getenv("OWM_LANG", "pl")
    units: str = os.getenv("OWM_UNITS", "metric")
    use_forecast16: bool = os.getenv("OWM_USE_FORECAST16", "false").lower() in {"1", "true", "yes"}
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
        """
        Prognoza dzienna (hierarchia prób):
        1) Forecast 16 days (/data/2.5/forecast/daily) – jeśli włączone i dozwolone.
        2) One Call 3.0 (/data/3.0/onecall) – daily do 8 dni.
        3) Fallback: 5-dniowy 3h (/data/2.5/forecast) → agregacja do dniówek.
        """
        # 1) forecast16, jeśli prosisz o niego
        if self.cfg.use_forecast16:
            try:
                url = "https://api.openweathermap.org/data/2.5/forecast/daily"
                params = {
                    "lat": lat, "lon": lon, "cnt": max(1, min(days, 16)),
                    "units": self.cfg.units, "lang": self.cfg.lang, "appid": self.cfg.api_key
                }
                r = await self._http.get(url, params=params)
                r.raise_for_status()
                return {"provider": "owm_forecast16", "data": r.json()}
            except httpx.HTTPStatusError as e:
                # jeśli to nie jest problem uprawnień – przekaż dalej
                if e.response.status_code not in (401, 403):
                    raise

        # 2) onecall3
        try:
            url = "https://api.openweathermap.org/data/3.0/onecall"
            params = {
                "lat": lat, "lon": lon, "exclude": "minutely,hourly,alerts",
                "units": self.cfg.units, "lang": self.cfg.lang, "appid": self.cfg.api_key
            }
            r = await self._http.get(url, params=params)
            r.raise_for_status()
            data = r.json()
            if "daily" in data:
                data["daily"] = data["daily"][:max(1, min(days, len(data["daily"])))]
            return {"provider": "owm_onecall3", "data": data}
        except httpx.HTTPStatusError as e:
            if e.response.status_code not in (401, 403):
                raise
            # 3) brak uprawnień → fallback do 5-dniowego 3h + agregacja
            return await self._forecast_from_5day_3h(lat, lon, days)

    async def _forecast_from_5day_3h(self, lat: float, lon: float, days: int) -> Dict[str, Any]:
        """Fallback: /data/2.5/forecast (5 dni / co 3h) → agregacja do dziennych min/max i POP."""
        url = "https://api.openweathermap.org/data/2.5/forecast"
        params = {
            "lat": lat, "lon": lon,
            "units": self.cfg.units, "lang": self.cfg.lang, "appid": self.cfg.api_key
        }
        r = await self._http.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        items = data.get("list") or []

        by_day: Dict[date, Dict[str, Any]] = {}
        for it in items:
            dday = datetime.fromtimestamp(int(it["dt"]), tz=timezone.utc).date()
            slot = by_day.setdefault(dday, {"tmins": [], "tmaxs": [], "pops": [], "descs": []})

            main = it.get("main") or {}
            temps: List[float] = []
            for key in ("temp_min", "temp_max", "temp"):
                val = main.get(key)
                if val is not None:
                    temps.append(float(val))
            if temps:
                slot["tmins"].append(min(temps))
                slot["tmaxs"].append(max(temps))

            try:
                slot["pops"].append(float(it.get("pop", 0) or 0))
            except Exception:
                pass

            desc = ((it.get("weather") or [{}])[0]).get("description")
            if desc:
                slot["descs"].append(desc)

        result_list: List[Dict[str, Any]] = []
        for dday in sorted(by_day.keys())[:max(1, min(days, 5))]:
            slot = by_day[dday]
            tmin = min(slot["tmins"]) if slot["tmins"] else None
            tmax = max(slot["tmaxs"]) if slot["tmaxs"] else None
            pop_day = max(slot["pops"]) if slot["pops"] else None
            desc = Counter(slot["descs"]).most_common(1)[0][0] if slot["descs"] else ""
            ts = int(datetime(dday.year, dday.month, dday.day, tzinfo=timezone.utc).timestamp())
            result_list.append({
                "dt": ts,
                "temp": {"min": tmin, "max": tmax},
                "pop": pop_day,
                "weather": [{"description": desc}],
            })

        city = data.get("city") or {}
        coord = city.get("coord") or {"lat": lat, "lon": lon}
        city["coord"] = coord
        out = {"city": city, "list": result_list}
        return {"provider": "owm_5day3h", "data": out}

def _i(x: Optional[float]) -> Optional[int]:
    try:
        return int(round(float(x)))
    except Exception:
        return None

def summarize_human(place_name: str, provider: str, raw: Dict[str, Any], days: int) -> Tuple[str, Dict[str, Any]]:
    """
    Zwięzła notatka 'human-readable' + metadane do KB (fallback regułowy – bez LLM).
    Zwraca: (title\\ntext, meta)
    """
    lines: List[str] = []
    coords = {"lat": None, "lon": None}
    start = end = None

    if provider in {"owm_forecast16", "owm_5day3h"}:
        city = (raw.get("city") or {})
        coords["lat"] = (city.get("coord") or {}).get("lat")
        coords["lon"] = (city.get("coord") or {}).get("lon")
        seq = list(islice(raw.get("list") or [], days))
        if seq:
            start = datetime.fromtimestamp(seq[0]["dt"], tz=timezone.utc).date()
            end   = datetime.fromtimestamp(seq[-1]["dt"], tz=timezone.utc).date()
        tmins = [_i((d.get("temp") or {}).get("min")) for d in seq if d.get("temp")]
        tmaxs = [_i((d.get("temp") or {}).get("max")) for d in seq if d.get("temp")]
        pops  = [float(d.get("pop", 0) or 0) for d in seq]
        wet   = sum(1 for p in pops if p >= 0.5)
        desc0 = ((seq[0].get("weather") or [{}])[0]).get("description", "") if seq else ""
    else:
        seq = list(islice(raw.get("daily") or [], days))
        if seq:
            start = datetime.fromtimestamp(seq[0]["dt"], tz=timezone.utc).date()
            end   = datetime.fromtimestamp(seq[-1]["dt"], tz=timezone.utc).date()
        tmins = [_i((d.get("temp") or {}).get("min")) for d in seq if d.get("temp")]
        tmaxs = [_i((d.get("temp") or {}).get("max")) for d in seq if d.get("temp")]
        pops  = [float(d.get("pop", 0) or 0) for d in seq]
        wet   = sum(1 for p in pops if p >= 0.5)
        desc0 = ((seq[0].get("weather") or [{}])[0]).get("description", "") if seq else ""

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
    meta = {"coords": coords, "provider": provider, "days_returned": len(seq)}
    title = f"Pogoda: {place_name} ({days} dni)"
    return f"{title}\n{text}", meta
