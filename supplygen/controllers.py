"""The three controllers compared in the benchmark.

StaticROP     - conventional static reorder-point policy (signal-blind baseline).
AdaptiveROP   - reorder point re-estimated from a moving window of sales (signal-blind).
ReactiveDual  - signal-blind, but notices overdue deliveries and re-sources (strong baseline).
SupplyGen     - static policy on the fast path; triage routes at-risk SKU-days to the council.
"""
from __future__ import annotations

import time

import numpy as np
from langgraph.types import Command

from .config import Policy
from .graph import build_graph
from .simulation import View, static_levels
from .triage import relevant_signals, triage

Order = tuple[int, int, int]   # (sku index, supplier id, quantity)


class StaticROP:
    name = "Static ROP"

    def __init__(self, policy: Policy | None = None):
        self.policy = policy or Policy()

    def reset(self, sim) -> None:
        self.rop, self.upto = static_levels(sim.m, self.policy)
        self.primary = [s["primary_supplier_id"] for s in sim.m.skus]

    def decide(self, view: View) -> list[Order]:
        pos = view.position
        return [(i, self.primary[i], int(np.ceil(self.upto[i] - pos[i])))
                for i in np.flatnonzero(pos <= self.rop)]

    def stats(self, sim) -> dict:
        return {}


class AdaptiveROP(StaticROP):
    name = "Adaptive ROP"

    def reset(self, sim) -> None:
        super().reset(sim)
        self.lead = np.array([sim.m.suppliers[p]["lead_time_days"] for p in self.primary])

    def decide(self, view: View) -> list[Order]:
        mu = view.sales_history[-14:].mean(axis=0)
        sigma = view.sales_history[-28:].std(axis=0)
        self.rop = mu * self.lead + self.policy.z * sigma * np.sqrt(self.lead)
        self.upto = self.rop + mu * self.policy.review_days
        return super().decide(view)


class ReactiveDual(StaticROP):
    """Reactive dual sourcing: no external signals, learns only from its own late orders.

    An order not received OVERDUE_DAYS after its quoted lead time marks that supplier as
    degraded for PENALTY_DAYS. While degraded, stuck orders are not counted as incoming
    stock and replenishment goes to the fastest healthy approved supplier.
    """
    name = "Reactive dual-source"
    OVERDUE_DAYS, PENALTY_DAYS = 2, 14

    def reset(self, sim) -> None:
        super().reset(sim)
        m = sim.m
        self.sup, self.mu, self.sigma = m.suppliers, m.mu, m.sigma
        self.approved = [m.approved[s["sku_id"]] for s in m.skus]
        self.open: list[list[list]] = [[] for _ in m.skus]   # per SKU: [supplier, qty, due day]
        self.bad_until: dict[int, int] = {}
        self.prev_on_order = np.zeros(len(m.skus), dtype=int)

    def decide(self, view: View) -> list[Order]:
        day, pol, orders = view.day, self.policy, []
        for i in range(len(self.open)):
            received = self.prev_on_order[i] - view.on_order[i]
            while received > 0 and self.open[i]:              # arrivals clear the oldest orders
                received -= self.open[i].pop(0)[1]
            stuck = 0
            for sup, qty, due in self.open[i]:
                if day > due + self.OVERDUE_DAYS:
                    self.bad_until[sup] = day + self.PENALTY_DAYS
                    stuck += qty
            healthy = [s for s in self.approved[i] if self.bad_until.get(s, -1) < day]
            sid = self.primary[i] if self.primary[i] in healthy or not healthy else \
                min(healthy, key=lambda s: self.sup[s]["lead_time_days"])
            lead = self.sup[sid]["lead_time_days"]
            rop = self.mu[i] * lead + pol.z * self.sigma[i] * np.sqrt(lead)
            pos = view.position[i] - stuck
            if pos <= rop:
                qty = int(np.ceil(rop + self.mu[i] * pol.review_days - pos))
                orders.append((i, sid, qty))
                self.open[i].append([sid, qty, day + lead])
        self.prev_on_order = view.on_order.copy()
        for i, _, qty in orders:
            self.prev_on_order[i] += qty
        return orders


class SupplyGen(StaticROP):
    name = "SupplyGen"

    def __init__(self, policy: Policy | None = None, name: str | None = None,
                 hitl_mode: str = "auto", graph=None, on_decision=None, approver=None,
                 llm_planner: bool = False):
        super().__init__(policy)
        self.name = name or self.name
        self.hitl_mode, self._graph, self.on_decision = hitl_mode, graph, on_decision
        self.llm_planner = llm_planner   # True: local LLM proposes supplier and quantity
        self.approver = approver   # callable(payload) -> "approve"/"reject", for interactive HITL

    def reset(self, sim) -> None:
        super().reset(sim)
        m = sim.m
        self.m, self.scenario, self.seed = m, sim.scenario, sim.seed
        self.graph = self._graph or build_graph(self.policy, m.episodes, llm_planner=self.llm_planner)
        # approved suppliers per SKU, primary first
        self.sups = [[m.suppliers[s] for s in m.approved[sku["sku_id"]]] for sku in m.skus]
        self.last_review = [-99] * len(m.skus)
        self.latency_ms: list[float] = []
        self.sku_days = self.invocations = self.true_hits = 0
        self.escalations = self.switches = self.clipped = self.holds = 0
        self._true_ids = {s["signal_id"] for s in sim.truth}

    def context(self, view: View, i: int) -> dict:
        return {"day": view.day, "sku": self.m.skus[i], "suppliers": self.sups[i],
                "on_hand": int(view.on_hand[i]), "position": float(view.position[i]),
                "mu": float(self.m.mu[i]), "sigma": float(self.m.sigma[i]),
                "rop": float(self.rop[i]), "recent_mean": float(view.sales_history[-14:, i].mean()),
                "last_review_day": self.last_review[i]}

    def decide(self, view: View) -> list[Order]:
        orders: list[Order] = []
        pos, pol = view.position, self.policy
        for i, sku in enumerate(self.m.skus):
            self.sku_days += 1
            signals = relevant_signals(view.signals, sku, self.sups[i], view.day, pol.lookahead_days)
            if pol.use_triage and not signals:           # nothing to analyse: fast path
                if pos[i] <= self.rop[i]:
                    orders.append((i, self.primary[i], int(np.ceil(self.upto[i] - pos[i]))))
                continue
            ctx = self.context(view, i)
            if pol.use_triage and not triage(ctx, signals, pol)["flag"]:
                if pos[i] <= self.rop[i]:
                    orders.append((i, self.primary[i], int(np.ceil(self.upto[i] - pos[i]))))
                continue
            # ---- council ----
            t0 = time.perf_counter()
            cfg = {"run_name": f"council {sku['sku_code']} day {view.day}",
                   "tags": [self.scenario, sku["priority_tier"]],
                   "metadata": {"scenario": self.scenario, "seed": self.seed, "sku": sku["sku_code"]},
                   "configurable": {"thread_id": f"{self.scenario}-{self.seed}-{sku['sku_id']}-{view.day}"}}
            out = self.graph.invoke({"ctx": ctx, "signals": signals, "hitl_mode": self.hitl_mode}, cfg)
            if "__interrupt__" in out:                   # paused for a human decision
                answer = self.approver(out["__interrupt__"][0].value) if self.approver else "approve"
                out = self.graph.invoke(Command(resume=answer), cfg)
            ms = (time.perf_counter() - t0) * 1000
            d = out["decision"]
            self.latency_ms.append(ms)
            self.invocations += 1
            self.last_review[i] = view.day
            accepted = {r["signal_id"] for r in out["analysis"]["supply_risks"] + out["analysis"]["demand_risks"]}
            self.true_hits += bool(accepted & self._true_ids)
            self.escalations += d["escalated"]
            self.switches += d["action"] == "switch_supplier"
            self.clipped += d["supervisor_status"] == "clipped"
            self.holds += d["action"] == "hold"
            if d["action"] != "hold":
                orders.append((i, d["chosen_supplier_id"], d["qty"]))
            if self.on_decision:
                self.on_decision({**d, "day": view.day, "sku_id": sku["sku_id"], "latency_ms": ms,
                                  "state": out})
        return orders

    def stats(self, sim) -> dict:
        lat = np.array(self.latency_ms) if self.latency_ms else np.array([0.0])
        return {"council_invocations": self.invocations,
                "invocation_rate": 100 * self.invocations / max(self.sku_days, 1),
                "triage_precision": 100 * self.true_hits / max(self.invocations, 1),
                "latency_ms_mean": float(lat.mean()), "latency_ms_p95": float(np.percentile(lat, 95)),
                "hitl_escalations": self.escalations, "supplier_switches": self.switches,
                "clipped_orders": self.clipped, "hold_decisions": self.holds}
