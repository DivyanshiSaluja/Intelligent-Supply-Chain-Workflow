"""The Council of Agents, the Supervisor and the audit logger.

Every agent is a pure function of the shared state that returns structured JSON-like
dicts, so the pipeline is deterministic, inspectable and traceable in LangSmith.
"""
from __future__ import annotations

import math
from typing import TypedDict

from langgraph.types import interrupt

from .config import Policy
from .scenarios import SUPPLY_TYPES, hits_category, hits_supplier
from .triage import signal_risk

# Generic effect-per-severity assumptions used when no precedent is available.
PRIORS = {"lead_mult_slope": 0.6, "lead_add_slope": 6.0, "fill_slope": 0.25, "demand_slope": 0.5}
TIER_SAFETY = {"critical": 1.3, "standard": 1.0, "low": 0.8}


class CouncilState(TypedDict, total=False):
    ctx: dict             # SKU, stock position, demand statistics, approved suppliers
    signals: list[dict]   # normalised external signals relevant to the SKU
    hitl_mode: str        # "auto" (simulated approver) or "interactive" (real interrupt)
    analysis: dict
    memory: dict
    forecast: dict
    ranking: list[dict]
    proposal: dict
    verdict: dict
    approved: bool
    decision: dict


def make_agents(policy: Policy, episodes: list[dict], llm_planner: bool = False) -> dict:
    """Build the node functions for one policy and one memory store."""

    def signal_analyst(state: CouncilState) -> dict:
        ctx = state["ctx"]
        supply, demand, rejected = [], [], []
        for s in state["signals"]:
            risk = signal_risk(s)
            if risk < policy.triage_threshold:
                rejected.append(s["signal_id"])
                continue
            item = {"signal_id": s["signal_id"], "signal_type": s["signal_type"],
                    "severity": s["severity_score"], "risk": round(risk, 3),
                    "start_day": s["start_day"], "end_day": s["end_day"],
                    "description": s["description"]}
            if s["signal_type"] in SUPPLY_TYPES:
                item["supplier_ids"] = [sp["supplier_id"] for sp in ctx["suppliers"] if hits_supplier(s, sp)]
                if item["supplier_ids"]:
                    supply.append(item)
            elif hits_category(s, ctx["sku"]["category_id"]):
                demand.append(item)
        parts = [f"{r['signal_type']} sev {r['severity']:.2f} on suppliers {r['supplier_ids']} "
                 f"days {r['start_day']}-{r['end_day']}" for r in supply]
        parts += [f"{r['signal_type']} sev {r['severity']:.2f} days {r['start_day']}-{r['end_day']}"
                  for r in demand]
        return {"analysis": {"supply_risks": supply, "demand_risks": demand,
                             "rejected_signal_ids": rejected,
                             "summary": "; ".join(parts) or "no credible disruption"}}

    def memory_recall(state: CouncilState) -> dict:
        cat = state["ctx"]["sku"]["category_id"]
        an = state["analysis"]
        memory = {}
        for stype in {r["signal_type"] for r in an["supply_risks"] + an["demand_risks"]}:
            eps = [e for e in episodes if e["signal_type"] == stype and e["category_id"] == cat]
            if not (policy.use_memory and eps):
                memory[stype] = {**PRIORS, "n_precedents": 0, "precedent_action": None}
                continue
            avg = lambda f: sum(f(e) for e in eps) / len(eps)
            memory[stype] = {
                "lead_mult_slope": round(avg(lambda e: (e["lead_mult"] - 1) / e["severity"]), 3),
                "lead_add_slope": round(avg(lambda e: e["lead_add"] / e["severity"]), 3),
                "fill_slope": round(avg(lambda e: (1 - e["fill_rate"]) / e["severity"]), 3),
                "demand_slope": round(avg(lambda e: (e["demand_mult"] - 1) / e["severity"]), 3),
                "n_precedents": len(eps), "precedent_action": eps[-1]["action_taken"]}
        return {"memory": memory}

    def demand_forecaster(state: CouncilState) -> dict:
        ctx, an = state["ctx"], state["analysis"]
        day, uplifts = ctx["day"], []
        if policy.use_forecaster:
            for r in an["demand_risks"]:
                slope = state["memory"][r["signal_type"]]["demand_slope"]
                uplifts.append({"start_day": r["start_day"], "end_day": r["end_day"],
                                "mult": round(1 + slope * r["severity"], 3)})
        surge_now = any(u["start_day"] <= day <= u["end_day"] for u in uplifts)
        # Recent sales already contain an ongoing surge, so only blend them in otherwise.
        base = ctx["mu"] if (surge_now or not policy.use_forecaster) else 0.5 * ctx["mu"] + 0.5 * ctx["recent_mean"]
        known = any(m["n_precedents"] for m in state["memory"].values())
        return {"forecast": {"base_daily": round(base, 2), "uplifts": uplifts,
                             "confidence": 0.9 if known or not uplifts else 0.6,
                             "contributing_signal_types": [r["signal_type"] for r in an["demand_risks"]]}}

    def supplier_evaluator(state: CouncilState) -> dict:
        ctx, an, day = state["ctx"], state["analysis"], state["ctx"]["day"]
        primary = ctx["suppliers"][0]
        ranking = []
        for sp in ctx["suppliers"] if policy.use_supplier_eval else [primary]:
            lead, fill, hit_by, upcoming_end = float(sp["lead_time_days"]), 1.0, [], None
            for r in an["supply_risks"]:
                if sp["supplier_id"] not in r["supplier_ids"]:
                    continue
                m, sev = state["memory"][r["signal_type"]], r["severity"]
                if r["start_day"] > day:               # not started: an order today ships normally
                    upcoming_end = max(upcoming_end or 0, r["end_day"])
                    continue
                hit_by.append(r["signal_type"])
                if r["signal_type"] == "supplier_failure":
                    lead += r["end_day"] - day + 1
                elif r["signal_type"] == "commodity_shortage":
                    lead *= 1 + m["lead_mult_slope"] * sev
                    fill *= max(0.2, 1 - m["fill_slope"] * sev)
                else:
                    lead += m["lead_add_slope"] * sev
            premium = sp["cost_mult"] / primary["cost_mult"] - 1
            score = lead / fill * (1 + 2 * max(0.0, premium)) / sp["reliability"]
            ranking.append({"supplier_id": sp["supplier_id"], "name": sp["name"],
                            "eff_lead": round(lead, 1), "fill": round(fill, 2),
                            "premium": round(premium, 3), "score": round(score, 2),
                            "affected_by": hit_by, "upcoming_risk_end": upcoming_end,
                            "is_primary": sp["supplier_id"] == primary["supplier_id"]})
        # Only consider leaving the primary when the primary itself is at risk (avoid churn).
        me = next(r for r in ranking if r["is_primary"])
        at_risk = bool(me["affected_by"]) or me["upcoming_risk_end"] is not None
        ranking.sort(key=lambda r: (not r["is_primary"]) if not at_risk
                     else r["score"] * (0.8 if r["is_primary"] else 1.0))
        return {"ranking": ranking}

    def replenishment_planner(state: CouncilState) -> dict:
        ctx, fc, best = state["ctx"], state["forecast"], state["ranking"][0]
        day, lead = ctx["day"], math.ceil(best["eff_lead"])
        horizon = lead + policy.review_days
        if best["upcoming_risk_end"] is not None:      # pre-build through the coming disruption
            horizon = max(horizon, best["upcoming_risk_end"] - day + lead)
        horizon = min(horizon, policy.max_order_days)

        def daily(d: int) -> float:
            mult = max([u["mult"] for u in fc["uplifts"] if u["start_day"] <= d <= u["end_day"]], default=1.0)
            return fc["base_daily"] * mult

        demand = sum(daily(d) for d in range(day, day + horizon))
        safety = policy.z * ctx["sigma"] * math.sqrt(lead) * TIER_SAFETY[ctx["sku"]["priority_tier"]]
        gap = demand + safety - ctx["position"]
        qty = math.ceil(max(0.0, gap) / best["fill"])
        if qty < 0.25 * ctx["mu"] * policy.review_days:
            action, qty = "hold", 0
        else:
            action = "reorder" if best["is_primary"] else "switch_supplier"
        return {"proposal": {"action": action, "qty": qty, "chosen_supplier_id": best["supplier_id"],
                             "cover_days": horizon, "forecast_demand": round(demand, 1),
                             "safety_stock": round(safety, 1)}}

    def llm_replenishment_planner(state: CouncilState) -> dict:
        """Local LLM chooses supplier and quantity; the rule-based plan is the fallback."""
        from .llm import plan_order
        rule = replenishment_planner(state)["proposal"]
        ctx, fc = state["ctx"], state["forecast"]
        out = plan_order({
            "today": ctx["day"], "sku": ctx["sku"]["name"], "priority": ctx["sku"]["priority_tier"],
            "stock_position_units": round(ctx["position"]),
            "forecast_units_per_day": fc["base_daily"],
            "demand_surges": [{"from_day": u["start_day"], "to_day": u["end_day"], "multiplier": u["mult"]}
                              for u in fc["uplifts"]],
            "usual_days_between_orders": policy.review_days,
            "disruptions": state["analysis"]["summary"],
            "suppliers": [{"supplier_id": r["supplier_id"], "name": r["name"], "is_usual_supplier": r["is_primary"],
                           "days_until_delivery_if_ordered_today": r["eff_lead"],
                           "share_of_order_expected_to_arrive": r["fill"],
                           "price_premium": r["premium"], "currently_disrupted_by": r["affected_by"]}
                          for r in state["ranking"]]})
        ids = {r["supplier_id"]: r for r in state["ranking"]}
        if not out["ok"] or out["supplier_id"] not in ids:
            return {"proposal": {**rule, "source": "rule_fallback", "llm_latency_s": out["latency_s"]}}
        qty = max(0, int(out["qty"]))
        action = "hold" if qty == 0 else "reorder" if ids[out["supplier_id"]]["is_primary"] else "switch_supplier"
        return {"proposal": {**rule, "action": action, "qty": qty, "chosen_supplier_id": out["supplier_id"],
                             "source": "llm", "llm_reason": out["reason"], "llm_latency_s": out["latency_s"],
                             "rule_action": rule["action"], "rule_qty": rule["qty"],
                             "rule_supplier_id": rule["chosen_supplier_id"]}}

    def supervisor(state: CouncilState) -> dict:
        ctx, p = state["ctx"], dict(state["proposal"])
        reasons, status = [], "approved"
        if p["action"] == "hold":
            return {"verdict": {"status": "approved", "reasons": ["no order needed"], **p}}
        by_id = {r["supplier_id"]: r for r in state["ranking"]}
        primary_id = ctx["suppliers"][0]["supplier_id"]
        if p["chosen_supplier_id"] not in {sp["supplier_id"] for sp in ctx["suppliers"]}:
            p.update(chosen_supplier_id=primary_id, action="reorder")
            status = "modified"; reasons.append("supplier not on the approved list; reverted to primary")
        premium = by_id.get(p["chosen_supplier_id"], {"premium": 0.0})["premium"]
        if premium > policy.max_cost_premium:
            p.update(chosen_supplier_id=primary_id, action="reorder"); premium = 0.0
            status = "modified"; reasons.append("cost premium above hard limit; reverted to primary")
        peak = max([u["mult"] for u in state["forecast"]["uplifts"]], default=1.0)
        cap = math.ceil(policy.max_order_days * ctx["mu"] * peak)
        if p["qty"] > cap:
            reasons.append(f"quantity clipped from {p['qty']} to cap {cap}")
            p["qty"] = cap; status = "clipped"
        value = p["qty"] * ctx["sku"]["unit_cost"] * (1 + premium)
        escalate = []
        if value > policy.approval_value:
            escalate.append(f"order value {value:,.0f} above approval limit")
        if p["action"] == "switch_supplier" and ctx["sku"]["priority_tier"] == "critical":
            escalate.append("supplier switch on a critical SKU")
        if premium >= policy.hitl_cost_premium:
            escalate.append(f"cost premium {premium:.0%}")
        return {"verdict": {"status": status, "reasons": reasons, "escalate": escalate,
                            "order_value": round(value, 2), **p}}

    def human_approval(state: CouncilState) -> dict:
        v, sku = state["verdict"], state["ctx"]["sku"]
        if state.get("hitl_mode") == "interactive":
            answer = interrupt({
                "question": "Approve this purchase order? (approve/reject)",
                "sku": f"{sku['sku_code']} {sku['name']} ({sku['priority_tier']})",
                "action": v["action"], "qty": v["qty"], "supplier_id": v["chosen_supplier_id"],
                "order_value": v["order_value"], "why_escalated": v["escalate"],
                "signals": state["analysis"]["summary"]})
            return {"approved": str(answer).strip().lower() in ("a", "approve", "approved", "y", "yes")}
        return {"approved": True}   # benchmark mode: a simulated approver accepts

    def audit_logger(state: CouncilState) -> dict:
        ctx, v, an, fc = state["ctx"], state["verdict"], state["analysis"], state["forecast"]
        sku, escalated = ctx["sku"], bool(v.get("escalate"))
        approved = state.get("approved", True)
        action, qty = (v["action"], v["qty"]) if approved else ("hold", 0)
        erp = ("none" if action == "hold" else "po_confirmed_after_approval" if escalated else "po_confirmed")
        if not approved:
            erp = "po_rejected_by_human"
        mem = "; ".join(f"{k}: {m['n_precedents']} precedents (usual action {m['precedent_action']})"
                        for k, m in state["memory"].items()) or "nothing to recall"
        top = state["ranking"][0]
        others = ", ".join(f"{r['name']} (lead {r['eff_lead']}d, fill {r['fill']:.0%})"
                           for r in state["ranking"][1:]) or "none"
        rationale = (
            f"Day {ctx['day']} | {sku['sku_code']} {sku['name']} [{sku['priority_tier']}] | "
            f"position {ctx['position']:.0f} units ({ctx['position'] / max(ctx['mu'], 0.1):.1f} days of cover). "
            f"Signal Analyst: {an['summary']}. Memory-Recall: {mem}. "
            f"Demand Forecaster: {fc['base_daily']}/day, uplifts {[u['mult'] for u in fc['uplifts']] or 'none'} "
            f"(confidence {fc['confidence']}). "
            f"Supplier Evaluator: best is {top['name']} (lead {top['eff_lead']}d, fill {top['fill']:.0%}, "
            f"cost {top['premium']:+.0%}); alternatives: {others}. "
            f"Replenishment Planner: {state['proposal']['action']} {state['proposal']['qty']} units to cover "
            f"{state['proposal']['cover_days']} days. "
            f"Supervisor: {v['status']}{' - ' + '; '.join(v['reasons']) if v['reasons'] else ''}"
            f"{'; escalated to human (' + '; '.join(v['escalate']) + ') -> ' + ('approved' if approved else 'rejected') if escalated else ''}. "
            f"ERP: {erp}.")
        return {"decision": {"action": action, "qty": qty,
                             "chosen_supplier_id": v["chosen_supplier_id"] if action != "hold" else None,
                             "supervisor_status": v["status"], "escalated": escalated,
                             "approved": approved, "erp_write_status": erp,
                             "rationale_text": rationale}}

    return {"signal_analyst": signal_analyst, "memory_recall": memory_recall,
            "demand_forecaster": demand_forecaster, "supplier_evaluator": supplier_evaluator,
            "replenishment_planner": llm_replenishment_planner if llm_planner else replenishment_planner, "supervisor": supervisor,
            "human_approval": human_approval, "audit_logger": audit_logger}
