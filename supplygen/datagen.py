"""Synthetic master data: categories, suppliers, SKUs, 12 months of demand, seeded memory."""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from .config import DATA_DIR, HISTORY_DAYS, MASTER_SEED
from .db import connect
from .scenarios import true_effects

CATEGORIES = [
    (1, "Electronics & Accessories", "semiconductors"),
    (2, "Grocery & Cooking Essentials", "edible_oil"),
    (3, "Apparel & Festive", "cotton"),
]
# id, name, region, category, commodity, lead time, reliability, cost multiplier
SUPPLIERS = [
    (1, "Shenzhen Electronics Co", "CN-South", 1, "semiconductors", 9, 0.93, 1.00),
    (2, "Chennai Components Ltd", "IN-South", 1, "semiconductors", 6, 0.90, 1.08),
    (3, "Hanoi Devices JSC", "VN-North", 1, "semiconductors", 11, 0.88, 0.97),
    (4, "Mumbai Agro Oils", "IN-West", 2, "edible_oil", 4, 0.95, 1.00),
    (5, "Jakarta Palm Traders", "ID-Java", 2, "edible_oil", 8, 0.90, 0.94),
    (6, "Delhi FMCG Distributors", "IN-North", 2, "diversified", 3, 0.92, 1.10),
    (7, "Tiruppur Textiles", "IN-South", 3, "cotton", 7, 0.92, 1.00),
    (8, "Dhaka Garments", "BD-Dhaka", 3, "cotton", 10, 0.87, 0.93),
]
PRODUCTS = {
    1: ["USB-C Charger 65W", "Wireless Earbuds", "Power Bank 20000mAh", "Smartwatch Band",
        "Bluetooth Speaker", "Phone Case", "HDMI Cable 2m", "Laptop Stand", "Webcam 1080p",
        "Mechanical Keyboard"],
    2: ["Sunflower Oil 1L", "Mustard Oil 1L", "Basmati Rice 5kg", "Wheat Flour 10kg",
        "Toor Dal 1kg", "Ghee 500ml", "Palm Oil 5L", "Sugar 5kg", "Instant Noodles 12pk",
        "Tea 1kg"],
    3: ["Cotton Kurta", "Festive Saree", "Kids Ethnic Set", "Cotton T-Shirt", "Denim Jeans",
        "Decor String Lights", "Gift Hamper Box", "Embroidered Dupatta", "Rangoli Kit",
        "Bedsheet Set"],
}
# Primary supplier and priority tier per product slot; chosen so every stress scenario
# touches critical SKUs (supplier 1, the oil suppliers 4/5 and the IN-South suppliers 2/7).
PRIMARY = {1: [1, 1, 1, 1, 2, 2, 1, 3, 2, 1], 2: [4, 4, 4, 6, 6, 4, 5, 6, 5, 4],
           3: [7, 7, 7, 7, 8, 8, 7, 7, 8, 7]}
TIER = {1: "ccssscslls", 2: "cccscslssl", 3: "ccsslsslcs"}
TIER_NAME = {"c": "critical", "s": "standard", "l": "low"}
WEEKLY = np.array([0.94, 0.92, 0.95, 0.97, 1.02, 1.12, 1.08])   # Mon..Sun demand factors
PAST_FESTIVAL = (300, 315, 0.8)   # (start, end, severity) of last year's festive window


def generate(db_path: Path | str | None = None, seed: int = MASTER_SEED) -> dict:
    rng = np.random.default_rng(seed)
    con = connect(db_path)
    for t in ("categories", "suppliers", "skus", "sku_suppliers", "demand_history",
              "memory_episodes", "disruption_events", "inventory_state", "decisions_log"):
        con.execute(f"DELETE FROM {t}")
    con.executemany("INSERT INTO categories VALUES (?,?,?)", CATEGORIES)
    con.executemany("INSERT INTO suppliers VALUES (?,?,?,?,?,?,?,?)", SUPPLIERS)

    skus, sku_id = [], 0
    for cat, names in PRODUCTS.items():
        for k, name in enumerate(names):
            sku_id += 1
            base = float(np.round(rng.uniform(6, 40), 1))
            cost = float(np.round(rng.uniform(4, 60), 2))
            skus.append((sku_id, f"SKU-{cat}{k:02d}", name, cat, TIER_NAME[TIER[cat][k]],
                         base, cost, PRIMARY[cat][k]))
            for s in SUPPLIERS:
                if s[3] == cat:
                    con.execute("INSERT INTO sku_suppliers VALUES (?,?,?)",
                                (sku_id, s[0], int(s[0] == PRIMARY[cat][k])))
    con.executemany("INSERT INTO skus VALUES (?,?,?,?,?,?,?,?)", skus)

    f0, f1, fsev = PAST_FESTIVAL
    hist = []
    for day in range(HISTORY_DAYS):
        for s in skus:
            lam = s[5] * WEEKLY[day % 7]
            if f0 <= day <= f1:
                lam *= true_effects("festival_surge", fsev, s[3])["demand_mult"]
            hist.append((day, s[0], int(rng.poisson(lam))))
    con.executemany("INSERT INTO demand_history VALUES (?,?,?)", hist)

    # Seeded memory: what past disruptions of each type actually did (noisy observations).
    episodes = []
    for stype in ("commodity_shortage", "supplier_failure", "weather_disruption", "festival_surge"):
        for cat in (1, 2, 3):
            for _ in range(3):
                sev = float(rng.uniform(0.5, 0.95))
                fx = true_effects(stype, sev, cat)
                noise = lambda v, base: base + (v - base) * float(rng.uniform(0.85, 1.15))
                action = {"commodity_shortage": "switch_supplier", "supplier_failure": "switch_supplier",
                          "weather_disruption": "reorder_early", "festival_surge": "pre_build"}[stype]
                episodes.append((stype, cat, round(sev, 3), round(noise(fx["lead_mult"], 1), 3),
                                 round(noise(fx["lead_add"], 0), 2), round(noise(fx["fill_rate"], 1), 3),
                                 round(noise(fx["demand_mult"], 1), 3), action, "no_stockout"))
    con.executemany("INSERT INTO memory_episodes (signal_type, category_id, severity, lead_mult,"
                    " lead_add, fill_rate, demand_mult, action_taken, outcome) VALUES (?,?,?,?,?,?,?,?,?)",
                    episodes)
    con.commit()

    # CSV exports so the synthetic dataset can be inspected or shared on its own.
    out = DATA_DIR / "csv"
    out.mkdir(parents=True, exist_ok=True)
    for table in ("categories", "suppliers", "skus", "sku_suppliers", "demand_history", "memory_episodes"):
        cur = con.execute(f"SELECT * FROM {table}")
        with open(out / f"{table}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow([c[0] for c in cur.description])
            w.writerows(cur.fetchall())
    con.close()
    return {"skus": len(skus), "suppliers": len(SUPPLIERS), "history_rows": len(hist),
            "memory_episodes": len(episodes)}
