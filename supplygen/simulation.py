"""Seeded stochastic inventory simulation and the metrics computed from a run."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .config import HOLDING_RATE, HORIZON_DAYS, ORDER_FIXED_COST, PRIORITY_WEIGHT, SCENARIOS, Policy
from .datagen import WEEKLY
from .db import Master
from .scenarios import SUPPLY_TYPES, build_signals, hits_supplier, public, true_effects


def static_levels(master: Master, policy: Policy) -> tuple[np.ndarray, np.ndarray]:
    """Classic reorder point and order-up-to level from 12 months of history."""
    lead = np.array([master.suppliers[s["primary_supplier_id"]]["lead_time_days"] for s in master.skus])
    rop = master.mu * lead + policy.z * master.sigma * np.sqrt(lead)
    return rop, rop + master.mu * policy.review_days


@dataclass
class View:
    """What a controller may observe on a given day."""
    day: int
    on_hand: np.ndarray
    on_order: np.ndarray
    signals: list[dict]        # published signals only, ground truth stripped
    sales_history: np.ndarray  # [days so far, n_skus] history followed by realised demand

    @property
    def position(self) -> np.ndarray:
        return self.on_hand + self.on_order


@dataclass
class RunResult:
    scenario: str
    seed: int
    controller: str
    metrics: dict
    cum_sbs: np.ndarray
    on_hand: np.ndarray        # [days, n_skus]
    unmet: np.ndarray
    demand: np.ndarray
    signals: list[dict] = field(default_factory=list)


class Simulation:
    def __init__(self, master: Master, scenario: str, seed: int, policy: Policy | None = None):
        self.m, self.scenario, self.seed = master, scenario, seed
        self.policy = policy or Policy()
        self.n = len(master.skus)
        self.signals = build_signals(scenario, seed, master)
        self.truth = [s for s in self.signals if s["_true"]]
        self.real = master.eval_demand is not None
        self.weights = np.array([PRIORITY_WEIGHT[s["priority_tier"]] for s in master.skus])
        self.unit_cost = np.array([s["unit_cost"] for s in master.skus])
        # Demand uses its own random stream so every controller faces identical demand.
        rng = np.random.default_rng([seed, SCENARIOS.index(scenario), 7])
        base = np.array([s["base_demand"] for s in master.skus])
        offset = master.history.shape[0]
        self.demand = np.zeros((HORIZON_DAYS, self.n), dtype=int)
        if self.real:
            # Replay a 120-day window of real demand. Supply scenarios use a random window;
            # the festival scenario is aligned so the signal starts with the real season.
            last = master.eval_demand.shape[0] - HORIZON_DAYS
            start = int(rng.integers(0, last + 1))
            if scenario == "festival_surge":
                sig = self.truth[0]
                start = min(last, master.peak_start - sig["start_day"])
                sig["end_day"] = HORIZON_DAYS - 1
            self.demand = master.eval_demand[start:start + HORIZON_DAYS].copy()
        for t in range(0 if not self.real else HORIZON_DAYS, HORIZON_DAYS):
            lam = base * WEEKLY[(offset + t) % 7]
            for sig in self.truth:
                if sig["signal_type"] == "festival_surge" and sig["start_day"] <= t <= sig["end_day"]:
                    lam = lam * np.array([true_effects("festival_surge", sig["severity_score"],
                                                       s["category_id"])["demand_mult"] for s in master.skus])
            self.demand[t] = rng.poisson(lam)

    # -- ground truth -----------------------------------------------------------------
    def _arrival(self, sku_i: int, supplier: dict, day: int, qty: int) -> tuple[int, int]:
        """Arrival day and delivered quantity of an order placed today."""
        mult, add, fill, ship = 1.0, 0, 1.0, day
        for sig in self.truth:
            if sig["start_day"] <= day <= sig["end_day"] and hits_supplier(sig, supplier):
                fx = true_effects(sig["signal_type"], sig["severity_score"])
                mult, add, fill = mult * fx["lead_mult"], add + fx["lead_add"], fill * fx["fill_rate"]
                if sig["signal_type"] == "supplier_failure":
                    ship = sig["end_day"] + 1
        r = np.random.default_rng([self.seed, 13, sku_i, day, supplier["supplier_id"]])
        late = 0 if r.random() < supplier["reliability"] else int(r.integers(1, 4))
        return ship + math.ceil(supplier["lead_time_days"] * mult) + add + late, int(round(qty * fill))

    def affected_skus(self) -> np.ndarray:
        """Indices of SKUs the real disruption touches (festival: all)."""
        sig = self.truth[0]
        if sig["signal_type"] not in SUPPLY_TYPES:
            return np.arange(self.n)
        return np.array([i for i, s in enumerate(self.m.skus)
                         if hits_supplier(sig, self.m.suppliers[s["primary_supplier_id"]])])

    # -- main loop --------------------------------------------------------------------
    def run(self, controller) -> RunResult:
        m, n = self.m, self.n
        rop, upto = static_levels(m, self.policy)
        on_hand = np.round(rop + 0.5 * (upto - rop)).astype(int)
        on_order = np.zeros(n, dtype=int)
        pipeline: dict[int, list[tuple[int, int, int]]] = {}
        unmet = np.zeros((HORIZON_DAYS, n), dtype=int)
        stock = np.zeros((HORIZON_DAYS, n), dtype=int)
        purchase = holding = fixed = 0.0
        n_orders = 0
        controller.reset(self)

        for t in range(HORIZON_DAYS):
            for i, delivered, ordered in pipeline.pop(t, []):
                on_hand[i] += delivered
                on_order[i] -= ordered
            view = View(t, on_hand.copy(), on_order.copy(),
                        [public(s) for s in self.signals if s["published_day"] <= t],
                        np.vstack([m.history, self.demand[:t]]))
            for i, supplier_id, qty in controller.decide(view):
                if qty <= 0:
                    continue
                sup = m.suppliers[supplier_id]
                arrival, delivered = self._arrival(i, sup, t, qty)
                pipeline.setdefault(max(arrival, t + 1), []).append((i, delivered, qty))
                on_order[i] += qty
                purchase += delivered * self.unit_cost[i] * sup["cost_mult"]
                fixed += ORDER_FIXED_COST
                n_orders += 1
            sold = np.minimum(on_hand, self.demand[t])
            unmet[t] = self.demand[t] - sold
            on_hand -= sold
            stock[t] = on_hand
            holding += float((on_hand * self.unit_cost).sum()) * HOLDING_RATE

        metrics = self._metrics(unmet, stock)
        metrics.update(purchase_cost=purchase, holding_cost=holding, order_cost=fixed,
                       total_cost=purchase + holding + fixed, n_orders=n_orders,
                       cost_per_unit_sold=(purchase + holding + fixed) / max(1, int((self.demand - unmet).sum())))
        metrics.update(controller.stats(self))
        cum = np.cumsum((unmet * self.weights).sum(axis=1))
        return RunResult(self.scenario, self.seed, controller.name, metrics, cum, stock, unmet,
                         self.demand, self.signals)

    def _metrics(self, unmet: np.ndarray, stock: np.ndarray) -> dict:
        w, d = self.weights, self.demand
        sbs = float((unmet * w).sum())
        sig = self.truth[0]
        lo, hi = sig["start_day"], min(HORIZON_DAYS, sig["end_day"] + 11)
        crit = np.array([i for i in self.affected_skus()
                         if self.m.skus[i]["priority_tier"] == "critical"], dtype=int)
        win = unmet[lo:hi][:, crit]
        return {
            "sbs": sbs,                                              # Stockout Burden Score
            "burden_pct": 100 * sbs / float((d * w).sum()),
            "fill_rate": 100 * (1 - unmet.sum() / d.sum()),
            "stockout_sku_days": int((unmet > 0).sum()),
            "critical_availability": 100 * float((win == 0).mean()),
            "critical_protection": 100 * float((win.sum(axis=0) == 0).mean()),
            "avg_inventory_units": float(stock.sum(axis=1).mean()),
        }
