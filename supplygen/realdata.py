"""Real-demand variant of the dataset, built from UCI Online Retail II.

Source: Chen, D. (2019). Online Retail II. UCI Machine Learning Repository (CC BY 4.0).
https://archive.ics.uci.edu/dataset/502/online+retail+ii
Two years of invoices of a UK online gift retailer (Dec 2009 - Dec 2011).

Only DEMAND is real. The dataset has no supplier or priority information, so the 30
best-selling products are mapped onto the same supplier / category / priority layout
as the synthetic dataset, and disruptions are injected exactly as before.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from .config import DATA_DIR, HISTORY_DAYS, MASTER_SEED
from .datagen import CATEGORIES, PRIMARY, SUPPLIERS, TIER, TIER_NAME
from .db import connect
from .scenarios import true_effects

RAW_DIR = DATA_DIR / "external" / "online_retail_ii"
DAILY_CSV = DATA_DIR / "real" / "online_retail_ii_daily_top30.csv"
REAL_DB = DATA_DIR / "real_demand.db"
PEAK_START = "2011-10-01"          # start of the real pre-Christmas season in the evaluation year
PRIOR_PEAK = ("2010-10-01", "2010-11-30")


def daily_top30() -> pd.DataFrame:
    """Daily units sold of the 30 most regularly sold products (cached as a small CSV)."""
    if DAILY_CSV.exists():
        return pd.read_csv(DAILY_CSV, index_col=0, parse_dates=True)
    xlsx = RAW_DIR / "online_retail_II.xlsx"
    if not xlsx.exists():
        with zipfile.ZipFile(RAW_DIR / "online_retail_ii.zip") as z:
            z.extractall(RAW_DIR)
    cols = ["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price"]
    df = pd.concat(pd.read_excel(xlsx, sheet_name=None, usecols=cols, dtype={"Invoice": str, "StockCode": str}).values())
    df = df[(df.Quantity > 0) & (df.Price > 0) & ~df.Invoice.str.startswith("C", na=False)]
    df = df[df.StockCode.str.match(r"^\d{5}[A-Za-z]?$", na=False)]          # real products only
    df["date"] = df.InvoiceDate.dt.normalize()
    daily = df.pivot_table(index="date", columns="StockCode", values="Quantity", aggfunc="sum", fill_value=0)
    daily = daily.reindex(pd.date_range(daily.index.min(), daily.index.max()), fill_value=0)
    half = len(daily) // 2
    active = np.minimum((daily.iloc[:half] > 0).sum(), (daily.iloc[half:] > 0).sum())  # sold all through both years
    top = active.sort_values(ascending=False).index[:30]
    out = daily[top].clip(upper=daily[top].quantile(0.995), axis=1).round().astype(int)   # trim bulk-order outliers
    price = df[df.StockCode.isin(top)].groupby("StockCode").Price.median()
    name = df[df.StockCode.isin(top)].groupby("StockCode").Description.agg(lambda s: str(s.mode().iloc[0]).title())
    out.columns = [f"{c}|{name[c]}|{price[c]:.2f}" for c in out.columns]
    DAILY_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(DAILY_CSV)
    return out


def generate_real(db_path: Path | str = REAL_DB) -> dict:
    daily = daily_top30()
    rng = np.random.default_rng(MASTER_SEED)
    con = connect(db_path)
    for t in ("categories", "suppliers", "skus", "sku_suppliers", "demand_history", "eval_demand",
              "memory_episodes"):
        con.execute(f"DELETE FROM {t}")
    con.executemany("INSERT INTO categories VALUES (?,?,?)", CATEGORIES)
    con.executemany("INSERT INTO suppliers VALUES (?,?,?,?,?,?,?,?)", SUPPLIERS)
    hist, ev = daily.iloc[:HISTORY_DAYS], daily.iloc[HISTORY_DAYS:]
    skus = []
    for j, col in enumerate(daily.columns):
        code, name, price = col.split("|")
        cat, k = j // 10 + 1, j % 10
        sku_id = j + 1
        skus.append((sku_id, f"UCI-{code}", name, cat, TIER_NAME[TIER[cat][k]], float(hist[col].mean()),
                     float(price), PRIMARY[cat][k]))
        for s in SUPPLIERS:
            if s[3] == cat:
                con.execute("INSERT INTO sku_suppliers VALUES (?,?,?)", (sku_id, s[0], int(s[0] == PRIMARY[cat][k])))
    con.executemany("INSERT INTO skus VALUES (?,?,?,?,?,?,?,?)", skus)
    for table, frame in (("demand_history", hist), ("eval_demand", ev)):
        con.executemany(f"INSERT INTO {table} VALUES (?,?,?)",
                        [(d, j + 1, int(v)) for d, row in enumerate(frame.to_numpy()) for j, v in enumerate(row)])

    # Memory: supply-side precedents as in the synthetic set; seasonal uplift measured from
    # the previous year's real peak (Oct-Nov 2010) per category.
    episodes = []
    for stype in ("commodity_shortage", "supplier_failure", "weather_disruption"):
        for cat in (1, 2, 3):
            for _ in range(3):
                sev = float(rng.uniform(0.5, 0.95))
                fx = true_effects(stype, sev, cat)
                n = lambda v, b: b + (v - b) * float(rng.uniform(0.85, 1.15))
                episodes.append((stype, cat, round(sev, 3), round(n(fx["lead_mult"], 1), 3), round(n(fx["lead_add"], 0), 2),
                                 round(n(fx["fill_rate"], 1), 3), 1.0, "switch_supplier", "no_stockout"))
    peak = hist.loc[PRIOR_PEAK[0]:PRIOR_PEAK[1]]
    for cat in (1, 2, 3):
        cols = daily.columns[(cat - 1) * 10: cat * 10]
        uplift = float(peak[cols].to_numpy().mean() / hist[cols].to_numpy().mean())
        episodes.append(("festival_surge", cat, 0.8, 1.0, 0.0, 1.0, round(uplift, 3), "pre_build", "observed 2010 season"))
    con.executemany("INSERT INTO memory_episodes (signal_type, category_id, severity, lead_mult, lead_add, fill_rate,"
                    " demand_mult, action_taken, outcome) VALUES (?,?,?,?,?,?,?,?,?)", episodes)
    con.execute("DELETE FROM meta")
    con.execute("INSERT INTO meta VALUES ('peak_start_index', ?)",
                (str(int((pd.Timestamp(PEAK_START) - ev.index[0]).days)),))
    con.commit(); con.close()
    return {"skus": len(skus), "history_days": len(hist), "evaluation_days": len(ev),
            "date_range": f"{daily.index[0].date()} to {daily.index[-1].date()}",
            "mean_daily_units_per_sku": round(float(daily.to_numpy().mean()), 1)}
