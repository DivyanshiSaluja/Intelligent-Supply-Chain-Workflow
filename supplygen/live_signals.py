"""Live external-signal ingestion, normalised into the disruption_events schema.

Sources (all free; only FRED needs a key):
  weather   Open-Meteo forecast for each supplier region
  holidays  Nager.Date public holidays (festival / sale windows)
  news      GDELT article search (classified by the local LLM if --llm is used)
  prices    FRED commodity series (needs FRED_API_KEY)
Raw API responses never reach the agents; only the normalised fields do.
"""
from __future__ import annotations

import datetime as dt
import os
import time

import requests

REGION_GEO = {"CN-South": (22.54, 114.06, "CN"), "IN-South": (13.08, 80.27, "IN"),
              "VN-North": (21.03, 105.85, "VN"), "IN-West": (19.08, 72.88, "IN"),
              "ID-Java": (-6.21, 106.85, "ID"), "IN-North": (28.61, 77.21, "IN"),
              "BD-Dhaka": (23.81, 90.41, "BD")}
NEWS_QUERY = '("edible oil" OR "palm oil" OR semiconductor OR cotton) (shortage OR disruption OR strike)'
FRED_SERIES = {"edible_oil": "PPOILUSDM", "cotton": "PCOTTINDUSDM"}
TIMEOUT = 20
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
# (date, name, expected demand severity 0-1) - major Indian retail festivals
FESTIVALS_IN = [("2026-10-20", "Dussehra", 0.6), ("2026-11-08", "Diwali", 0.9),
                ("2026-12-25", "Christmas", 0.4), ("2027-01-26", "Republic Day sales", 0.5),
                ("2027-03-22", "Holi", 0.5)]


def _event(stype, start, end, severity, credibility, description, **kw) -> dict:
    return {"source": "live", "signal_type": stype, "published_day": 0, "start_day": start,
            "end_day": end, "affected_supplier_id": None, "affected_region": kw.get("region"),
            "affected_commodity": kw.get("commodity"), "affected_category_id": kw.get("category_id"),
            "severity_score": round(severity, 3), "credibility": credibility, "description": description}


def weather() -> list[dict]:
    out = []
    for region, (lat, lon, _) in REGION_GEO.items():
        r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=TIMEOUT, params={
            "latitude": lat, "longitude": lon, "forecast_days": 7, "timezone": "UTC",
            "daily": "precipitation_sum,wind_speed_10m_max"}).json()["daily"]
        for d, (rain, wind) in enumerate(zip(r["precipitation_sum"], r["wind_speed_10m_max"])):
            sev = max(min((rain or 0) / 120, 1.0), min((wind or 0) / 100, 1.0))   # 120 mm/day or 100 km/h = 1.0
            if sev >= 0.3:
                out.append(_event("weather_disruption", d, d + 3, sev, 0.9, region=region,
                                  description=f"{region}: forecast {rain} mm rain, wind {wind} km/h on {r['time'][d]}"))
    return out


def holidays(horizon_days: int = 45) -> list[dict]:
    """Festival / sale windows in the selling country (SALES_COUNTRY, default IN).

    Nager.Date is used when it covers the country; it has no data for India, so the
    built-in FESTIVALS_IN calendar is the fallback (verify the dates before relying on them).
    """
    today, country = dt.date.today(), os.getenv("SALES_COUNTRY", "IN")
    resp = requests.get(f"https://date.nager.at/api/v3/NextPublicHolidays/{country}", timeout=TIMEOUT)
    if resp.status_code == 200 and resp.text.strip():
        days = [(h["date"], h["name"], 0.5) for h in resp.json()]
    else:
        days = FESTIVALS_IN if country == "IN" else []
    out = []
    for date, name, sev in days:
        d = (dt.date.fromisoformat(date) - today).days
        if 0 <= d <= horizon_days:
            out.append(_event("festival_surge", max(0, d - 7), d + 2, sev, 1.0,
                              description=f"{name} on {date} ({country}): festive demand window"))
    return out


def news(use_llm: bool = False, max_records: int = 8) -> list[dict]:
    params = {
        "query": NEWS_QUERY + " sourcelang:english", "mode": "ArtList", "format": "json",
        "maxrecords": max_records, "timespan": "3d", "sort": "DateDesc"}
    r = requests.get(GDELT_URL, timeout=TIMEOUT, params=params)
    if r.status_code == 429:                 # GDELT allows one request every 5 seconds
        time.sleep(6)
        r = requests.get(GDELT_URL, timeout=TIMEOUT, params=params)
    r.raise_for_status()
    arts = r.json().get("articles", []) if r.text.strip().startswith("{") else []
    out = []
    for a in arts:
        title = a["title"]
        if use_llm:
            from .llm import classify_headline
            c = classify_headline(title, ["semiconductors", "edible_oil", "cotton"], list(REGION_GEO))
            if c["signal_type"] == "irrelevant":
                continue
            out.append(_event(c["signal_type"], 0, 14, c["severity_score"], 0.6, f"[{a['domain']}] {title}",
                              commodity=c["affected_commodity"], region=c["affected_region"]))
        else:   # keyword rule when no LLM is used
            low = title.lower()
            com = ("edible_oil" if "oil" in low else "semiconductors" if "semiconductor" in low or "chip" in low
                   else "cotton" if "cotton" in low else None)
            if com:
                out.append(_event("commodity_shortage", 0, 14, 0.5, 0.5, f"[{a['domain']}] {title}", commodity=com))
    return out


def prices() -> list[dict]:
    key, out = os.getenv("FRED_API_KEY"), []
    if not key:
        return out
    for commodity, series in FRED_SERIES.items():
        obs = requests.get("https://api.stlouisfed.org/fred/series/observations", timeout=TIMEOUT, params={
            "series_id": series, "api_key": key, "file_type": "json", "sort_order": "desc", "limit": 4}).json()["observations"]
        vals = [float(o["value"]) for o in obs if o["value"] != "."]
        if len(vals) >= 2:
            change = vals[0] / vals[-1] - 1
            if change > 0.05:   # a >5% rise over the window is treated as a tightening signal
                out.append(_event("commodity_shortage", 0, 30, min(1.0, change * 4), 0.95, commodity=commodity,
                                  description=f"{series} up {change:.1%} over {len(vals)} months (latest {obs[0]['date']})"))
    return out


def fetch_all(use_llm: bool = False) -> tuple[list[dict], dict]:
    """Fetch every source; a failing source is reported, not fatal."""
    events, status = [], {}
    for name, fn in (("weather", weather), ("holidays", holidays),
                     ("news", lambda: news(use_llm)), ("prices", prices)):
        try:
            got = fn()
            events += got
            status[name] = f"ok ({len(got)} events)"
        except Exception as exc:
            status[name] = f"failed: {type(exc).__name__}: {exc}"[:160]
    if not os.getenv("FRED_API_KEY"):
        status["prices"] = "skipped (set FRED_API_KEY)"
    events = [e for e in events if e["severity_score"] > 0]
    for i, e in enumerate(events, 1):
        e["signal_id"] = i
    return events, status
