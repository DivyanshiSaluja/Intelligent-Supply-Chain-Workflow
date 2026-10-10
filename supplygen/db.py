"""SQLite schema and data-access helpers (the lightweight 'data warehouse')."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    category_id INTEGER PRIMARY KEY, name TEXT, commodity TEXT);
CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id INTEGER PRIMARY KEY, name TEXT, region TEXT, category_id INTEGER,
    commodity TEXT, lead_time_days INTEGER, reliability REAL, cost_mult REAL);
CREATE TABLE IF NOT EXISTS skus (
    sku_id INTEGER PRIMARY KEY, sku_code TEXT, name TEXT, category_id INTEGER,
    priority_tier TEXT, base_demand REAL, unit_cost REAL, primary_supplier_id INTEGER);
CREATE TABLE IF NOT EXISTS sku_suppliers (
    sku_id INTEGER, supplier_id INTEGER, is_primary INTEGER,
    PRIMARY KEY (sku_id, supplier_id));
CREATE TABLE IF NOT EXISTS demand_history (
    day INTEGER, sku_id INTEGER, qty INTEGER, PRIMARY KEY (day, sku_id));
CREATE TABLE IF NOT EXISTS memory_episodes (
    episode_id INTEGER PRIMARY KEY AUTOINCREMENT, signal_type TEXT, category_id INTEGER,
    severity REAL, lead_mult REAL, lead_add REAL, fill_rate REAL, demand_mult REAL,
    action_taken TEXT, outcome TEXT);
-- real-demand variant only: demand after the history year, and dataset facts
CREATE TABLE IF NOT EXISTS eval_demand (
    day INTEGER, sku_id INTEGER, qty INTEGER, PRIMARY KEY (day, sku_id));
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
-- written by runs --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS disruption_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, source TEXT, signal_type TEXT,
    published_day INTEGER, start_day INTEGER, end_day INTEGER,
    affected_supplier_id INTEGER, affected_region TEXT, affected_commodity TEXT,
    affected_category_id INTEGER, severity_score REAL, credibility REAL, description TEXT);
CREATE TABLE IF NOT EXISTS inventory_state (
    run_id TEXT, controller TEXT, day INTEGER, sku_id INTEGER, on_hand INTEGER,
    on_order INTEGER, demand INTEGER, unmet INTEGER,
    PRIMARY KEY (run_id, controller, day, sku_id));
CREATE TABLE IF NOT EXISTS decisions_log (
    decision_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, day INTEGER, sku_id INTEGER,
    action TEXT, qty INTEGER, chosen_supplier_id INTEGER, supervisor_status TEXT,
    escalated INTEGER, approved INTEGER, erp_write_status TEXT, latency_ms REAL,
    rationale_text TEXT);
"""


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


@dataclass
class Master:
    """Master data loaded once and shared by every simulation run."""
    categories: dict[int, dict]
    suppliers: dict[int, dict]
    skus: list[dict]                  # ordered by sku_id; index = position in arrays
    approved: dict[int, list[int]]    # sku_id -> approved supplier ids
    history: np.ndarray               # [HISTORY_DAYS, n_skus] daily demand
    mu: np.ndarray                    # mean daily demand per SKU (from history)
    sigma: np.ndarray                 # std of daily demand per SKU (from history)
    episodes: list[dict]              # seeded memory of past disruptions
    eval_demand: np.ndarray | None = None   # real demand to replay (None = synthetic Poisson)
    peak_start: int | None = None           # index in eval_demand where the real season starts


def load_master(path: Path | str | None = None) -> Master:
    con = connect(path)
    rows = lambda q: [dict(r) for r in con.execute(q)]
    categories = {r["category_id"]: r for r in rows("SELECT * FROM categories")}
    suppliers = {r["supplier_id"]: r for r in rows("SELECT * FROM suppliers")}
    skus = rows("SELECT * FROM skus ORDER BY sku_id")
    if not skus:
        raise RuntimeError("Database is empty. Run: python scripts/generate_data.py")
    approved: dict[int, list[int]] = {}
    for r in rows("SELECT * FROM sku_suppliers ORDER BY sku_id, is_primary DESC, supplier_id"):
        approved.setdefault(r["sku_id"], []).append(r["supplier_id"])
    idx = {s["sku_id"]: i for i, s in enumerate(skus)}
    hist = rows("SELECT * FROM demand_history")
    n_days = max(h["day"] for h in hist) + 1
    history = np.zeros((n_days, len(skus)), dtype=int)
    for h in hist:
        history[h["day"], idx[h["sku_id"]]] = h["qty"]
    episodes = rows("SELECT * FROM memory_episodes")
    ev = rows("SELECT * FROM eval_demand")
    eval_demand = None
    if ev:
        eval_demand = np.zeros((max(e["day"] for e in ev) + 1, len(skus)), dtype=int)
        for e in ev:
            eval_demand[e["day"], idx[e["sku_id"]]] = e["qty"]
    meta = {r["key"]: r["value"] for r in rows("SELECT * FROM meta")}
    con.close()
    return Master(categories, suppliers, skus, approved, history,
                  history.mean(axis=0), history.std(axis=0), episodes, eval_demand,
                  int(meta["peak_start_index"]) if "peak_start_index" in meta else None)
