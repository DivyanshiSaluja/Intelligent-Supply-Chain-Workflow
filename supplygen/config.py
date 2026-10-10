"""Central configuration for the SupplyGen prototype."""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"
FIGURES_DIR = ROOT / "figures"
DB_PATH = Path(os.getenv("SUPPLYGEN_DB", DATA_DIR / "supplygen.db"))

MASTER_SEED = 42          # seed of the master data (SKUs, suppliers, history)
HISTORY_DAYS = 365        # 12 months of daily demand history
HORIZON_DAYS = 120        # evaluation horizon of every scenario run

PRIORITY_WEIGHT = {"critical": 3, "standard": 2, "low": 1}
SCENARIOS = ["commodity_shortage", "supplier_failure", "weather_disruption", "festival_surge"]
SCENARIO_LABEL = {
    "commodity_shortage": "A: Commodity shortage",
    "supplier_failure": "B: Supplier failure",
    "weather_disruption": "C: Weather disruption",
    "festival_surge": "D: Festival surge",
}

HOLDING_RATE = 0.001      # holding cost per unit-day as a fraction of unit cost
ORDER_FIXED_COST = 40.0   # fixed cost per purchase order


@dataclass(frozen=True)
class Policy:
    """Tunable parameters of the controllers and guardrails."""
    z: float = 1.65                    # service factor of the reorder point
    review_days: int = 14              # order cycle used for order-up-to levels
    # --- triage ---
    triage_threshold: float = 0.50     # minimum signal risk (severity x credibility)
    lookahead_days: int = 30           # how far ahead an upcoming signal is considered
    cooldown_days: int = 5            # days before the council reviews the same SKU again
    # --- supervisor guardrails ---
    max_order_days: int = 60           # an order may never exceed this many days of demand
    max_cost_premium: float = 0.25     # supplier switch rejected above this premium
    hitl_cost_premium: float = 0.10    # switch escalated to a human at/above this premium
    approval_value: float = 30000.0    # order value escalated to a human above this
    # --- ablation switches ---
    use_triage: bool = True
    use_memory: bool = True
    use_forecaster: bool = True
    use_supplier_eval: bool = True

    def but(self, **kw) -> "Policy":
        return replace(self, **kw)
