"""Signal-triage: a cheap screen that decides which SKU-days deserve the full council."""
from __future__ import annotations

from .config import Policy
from .scenarios import SUPPLY_TYPES, hits_category, hits_supplier


def signal_risk(signal: dict) -> float:
    return signal["severity_score"] * signal["credibility"]


def relevant_signals(signals: list[dict], sku: dict, suppliers: list[dict], day: int,
                     lookahead: int) -> list[dict]:
    """Published, unexpired signals touching the SKU's category or any approved supplier."""
    out = []
    for s in signals:
        if s["published_day"] > day or s["end_day"] < day or s["start_day"] - day > lookahead:
            continue
        if hits_category(s, sku["category_id"]) or any(hits_supplier(s, sp) for sp in suppliers):
            out.append(s)
    return out


def triage(ctx: dict, signals: list[dict], policy: Policy) -> dict:
    """Flag a SKU-day when a credible signal meets a risk-adjusted cover shortfall.

    ctx needs: day, position, mu, sigma, rop, sku, suppliers (primary first), last_review_day.
    """
    primary = ctx["suppliers"][0]
    risky = [s for s in signals if signal_risk(s) >= policy.triage_threshold
             and (hits_supplier(s, primary) or hits_category(s, ctx["sku"]["category_id"]))]
    if not risky:
        return {"flag": False, "risk": 0.0, "reason": "no credible signal for this SKU"}
    risk = max(signal_risk(s) for s in risky)
    if ctx["day"] - ctx.get("last_review_day", -99) < policy.cooldown_days and ctx["position"] > ctx["rop"]:
        return {"flag": False, "risk": risk, "reason": "reviewed recently (cooldown)"}

    lead, mu, day = primary["lead_time_days"], ctx["mu"], ctx["day"]
    need = ctx["rop"]
    if any(s["signal_type"] in SUPPLY_TYPES for s in risky):
        need = max(need, ctx["rop"] + risk * policy.review_days * mu)
    for s in risky:
        if s["signal_type"] == "festival_surge":
            horizon = lead + int(round(risk * policy.review_days))
            days_in = sum(1 for d in range(day, day + horizon) if s["start_day"] <= d <= s["end_day"])
            surge = mu * (horizon + days_in * s["severity_score"])
            need = max(need, surge + (ctx["rop"] - mu * lead))
    flag = ctx["position"] < need
    return {"flag": flag, "risk": round(risk, 3),
            "reason": (f"position {ctx['position']:.0f} below risk-adjusted need {need:.0f}"
                       if flag else "cover is sufficient despite the signal")}
