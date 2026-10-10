"""Stress scenarios: the external signals each run sees and their ground-truth effects.

A signal is what the agents can read (type, window, target, severity, credibility,
headline). Keys starting with '_' are ground truth used only by the simulator.
"""
from __future__ import annotations

import numpy as np

from .config import HORIZON_DAYS, SCENARIOS

SUPPLY_TYPES = {"commodity_shortage", "supplier_failure", "weather_disruption"}
FESTIVAL_SLOPE = {1: 0.7, 2: 0.5, 3: 1.8}   # demand uplift per unit severity, by category


def true_effects(signal_type: str, severity: float, category_id: int | None = None) -> dict:
    """Ground-truth physical effect of a real disruption of a given severity."""
    fx = {"lead_mult": 1.0, "lead_add": 0, "fill_rate": 1.0, "demand_mult": 1.0}
    if signal_type == "commodity_shortage":
        fx["lead_mult"] = 1 + 1.5 * severity
        fx["fill_rate"] = 1 - 0.6 * severity
    elif signal_type == "weather_disruption":
        fx["lead_add"] = int(round(4 + 10 * severity))
    elif signal_type == "festival_surge":
        fx["demand_mult"] = 1 + FESTIVAL_SLOPE.get(category_id, 0.5) * severity
    return fx


def _signal(sid, stype, published, start, end, severity, credibility, description, true,
            supplier_id=None, region=None, commodity=None, category_id=None, source="replay"):
    return {
        "signal_id": sid, "source": source, "signal_type": stype,
        "published_day": int(published), "start_day": int(start), "end_day": int(end),
        "affected_supplier_id": supplier_id, "affected_region": region,
        "affected_commodity": commodity, "affected_category_id": category_id,
        "severity_score": round(float(severity), 3), "credibility": round(float(credibility), 3),
        "description": description, "_true": true,
    }


def build_signals(scenario: str, seed: int, master) -> list[dict]:
    """One real disruption for the scenario plus background false alarms."""
    rng = np.random.default_rng([seed, SCENARIOS.index(scenario), 101])
    sev = rng.uniform(0.65, 0.95)
    cred = rng.uniform(0.85, 1.0)
    sup = master.suppliers
    out: list[dict] = []

    if scenario == "commodity_shortage":
        start = rng.integers(30, 46); end = start + rng.integers(30, 46)
        out.append(_signal(1, scenario, start - rng.integers(3, 8), start, end, sev, cred,
                           "Edible-oil futures spike as conflict disrupts tanker routes; "
                           "refiners warn of rationed allocations.", True, commodity="edible_oil"))
    elif scenario == "supplier_failure":
        s = sup[1]
        start = rng.integers(30, 46); end = start + 20 + int(round(20 * sev))
        out.append(_signal(1, scenario, start + rng.integers(0, 3), start, end, sev, cred,
                           f"{s['name']} halts all shipments after a plant shutdown; "
                           "restart date uncertain.", True, supplier_id=1))
    elif scenario == "weather_disruption":
        start = rng.integers(35, 51); end = start + rng.integers(12, 19)
        out.append(_signal(1, scenario, start - rng.integers(2, 5), start, end, sev, cred,
                           "Cyclone warning for IN-South: ports and highways expected to "
                           "close, freight delays likely.", True, region="IN-South"))
    elif scenario == "festival_surge":
        start = rng.integers(50, 66); end = start + rng.integers(12, 19)
        out.append(_signal(1, scenario, start - 28, start, end, sev, cred,
                           "Festive season sale window announced; marketplaces forecast "
                           "record order volumes.", True))
    else:
        raise ValueError(f"unknown scenario {scenario}")

    # Background noise: weak reports and loud-but-unreliable rumours with no real effect.
    types = sorted(SUPPLY_TYPES | {"festival_surge"})
    for k in range(8):
        stype = types[rng.integers(len(types))]
        rumour = k >= 6
        n_sev = rng.uniform(0.70, 0.95) if rumour else rng.uniform(0.15, 0.45)
        n_cred = rng.uniform(0.30, 0.58) if rumour else rng.uniform(0.40, 0.90)
        start = rng.integers(5, HORIZON_DAYS - 20); end = start + rng.integers(7, 21)
        kw, what = {}, "regional demand"
        if stype == "supplier_failure":
            sid = int(rng.integers(1, len(sup) + 1)); kw["supplier_id"] = sid
            what = sup[sid]["name"]
        elif stype == "weather_disruption":
            kw["region"] = what = sorted({s["region"] for s in sup.values()})[rng.integers(6)]
        elif stype == "commodity_shortage":
            kw["commodity"] = what = ["semiconductors", "edible_oil", "cotton"][rng.integers(3)]
        else:
            kw["category_id"] = int(rng.integers(1, 4))
        text = (f"Unverified social-media rumour of {stype.replace('_', ' ')} affecting {what}."
                if rumour else f"Minor report: possible {stype.replace('_', ' ')} ({what}).")
        out.append(_signal(len(out) + 1, stype, start - rng.integers(1, 6), start, end,
                           n_sev, n_cred, text, False, **kw))
    return out


def public(signal: dict) -> dict:
    """The view of a signal the agents are allowed to see (no ground truth)."""
    return {k: v for k, v in signal.items() if not k.startswith("_")}


def hits_supplier(signal: dict, supplier: dict) -> bool:
    """Does a supply-side signal touch this supplier?"""
    if signal["signal_type"] not in SUPPLY_TYPES:
        return False
    return (signal["affected_supplier_id"] == supplier["supplier_id"]
            or (signal["affected_region"] is not None and signal["affected_region"] == supplier["region"])
            or (signal["affected_commodity"] is not None and signal["affected_commodity"] == supplier["commodity"]))


def hits_category(signal: dict, category_id: int) -> bool:
    """Does a demand-side signal touch this category?"""
    return (signal["signal_type"] == "festival_surge"
            and signal["affected_category_id"] in (None, category_id))
