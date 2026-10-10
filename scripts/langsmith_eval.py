"""Decision-level evaluation of the council against the static baseline.

Builds a dataset of 'reorder moments' (a SKU at its reorder point while a disruption is
live), runs both the SupplyGen council and the static reorder-point rule on each, and
scores them with four evaluators.

    python scripts/langsmith_eval.py              # local scoring, no account needed
    python scripts/langsmith_eval.py --upload     # also create a LangSmith dataset and two
                                                  # experiments you can compare side by side
--upload needs LANGSMITH_API_KEY (put it in .env).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from supplygen.config import RESULTS_DIR, SCENARIOS, Policy
from supplygen.db import load_master
from supplygen.graph import build_graph
from supplygen.scenarios import SUPPLY_TYPES, hits_supplier, public
from supplygen.simulation import Simulation, static_levels
from supplygen.triage import relevant_signals

DATASET = "supplygen-reorder-moments"
POLICY = Policy()
MASTER = load_master()
ROP, UPTO = static_levels(MASTER, POLICY)
GRAPH = build_graph(POLICY, MASTER.episodes)


def build_examples(seeds: int = 5) -> list[dict]:
    examples = []
    for sc in SCENARIOS:
        for seed in range(seeds):
            sim = Simulation(MASTER, sc, seed, POLICY)
            true = sim.truth[0]
            supply = true["signal_type"] in SUPPLY_TYPES
            day = max(true["published_day"], true["start_day"]) + 2 if supply else true["start_day"] - 5
            visible = [public(s) for s in sim.signals if s["published_day"] <= day]
            affected = set(sim.affected_skus().tolist())
            picks = sorted(affected)[:3] + [i for i in range(len(MASTER.skus)) if i not in affected][:2]
            for i in picks[:5]:
                sku = MASTER.skus[i]
                sups = [MASTER.suppliers[s] for s in MASTER.approved[sku["sku_id"]]]
                pos = float(round(ROP[i] * 0.95))
                examples.append({
                    "inputs": {"ctx": {"day": day, "sku": sku, "suppliers": sups, "on_hand": int(pos),
                                       "position": pos, "mu": float(MASTER.mu[i]), "sigma": float(MASTER.sigma[i]),
                                       "rop": float(ROP[i]), "recent_mean": float(MASTER.history[-14:, i].mean()),
                                       "last_review_day": -99},
                               "signals": relevant_signals(visible, sku, sups, day, POLICY.lookahead_days),
                               "static_qty": int(math.ceil(UPTO[i] - pos))},
                    "outputs": {"scenario": sc, "should_protect": i in affected, "supply_side": supply,
                                "disrupted_supplier_ids": [s["supplier_id"] for s in sups if supply and hits_supplier(true, s)],
                                "qty_cap": int(math.ceil(POLICY.max_order_days * MASTER.mu[i] * 3))}})
    return examples


# ---- targets ---------------------------------------------------------------------------
def supplygen_target(inputs: dict) -> dict:
    d = GRAPH.invoke({"ctx": inputs["ctx"], "signals": inputs["signals"], "hitl_mode": "auto"})["decision"]
    return {k: d[k] for k in ("action", "qty", "chosen_supplier_id", "escalated", "rationale_text")}


def static_target(inputs: dict) -> dict:
    return {"action": "reorder", "qty": inputs["static_qty"], "escalated": False, "rationale_text": "",
            "chosen_supplier_id": inputs["ctx"]["suppliers"][0]["supplier_id"]}


# ---- evaluators ------------------------------------------------------------------------
def avoids_disrupted_supplier(outputs: dict, reference_outputs: dict) -> bool:
    return outputs["action"] == "hold" or outputs["chosen_supplier_id"] not in reference_outputs["disrupted_supplier_ids"]


def protective_action(inputs: dict, outputs: dict, reference_outputs: dict) -> bool:
    """Affected SKU: switch supplier or order clearly more than usual. Unaffected: do not over-react."""
    if not reference_outputs["should_protect"]:
        return outputs["action"] != "switch_supplier"
    return outputs["action"] == "switch_supplier" or outputs["qty"] >= 1.15 * inputs["static_qty"]


def within_guardrails(outputs: dict, reference_outputs: dict) -> bool:
    return outputs["qty"] <= reference_outputs["qty_cap"]


def has_rationale(outputs: dict) -> bool:
    return len(outputs["rationale_text"]) > 80


def run_local(examples: list[dict]) -> dict:
    table = {}
    for name, target in (("Static ROP", static_target), ("SupplyGen", supplygen_target)):
        scores = {"avoids_disrupted_supplier": [], "protective_action": [], "within_guardrails": [], "has_rationale": []}
        for ex in examples:
            out, ref = target(ex["inputs"]), ex["outputs"]
            scores["avoids_disrupted_supplier"].append(avoids_disrupted_supplier(out, ref))
            scores["protective_action"].append(protective_action(ex["inputs"], out, ref))
            scores["within_guardrails"].append(within_guardrails(out, ref))
            scores["has_rationale"].append(has_rationale(out))
        table[name] = {k: round(100 * sum(v) / len(v), 1) for k, v in scores.items()}
    return table


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--upload", action="store_true")
    a = ap.parse_args()
    examples = build_examples(a.seeds)
    table = run_local(examples)
    print(f"{len(examples)} reorder moments\n")
    print(f"{'evaluator (% passed)':30s}{'Static ROP':>12s}{'SupplyGen':>12s}")
    for k in table["SupplyGen"]:
        print(f"{k:30s}{table['Static ROP'][k]:12.1f}{table['SupplyGen'][k]:12.1f}")
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "decision_eval.json").write_text(json.dumps({"n": len(examples), "scores": table}, indent=1))

    if a.upload:
        from langsmith import Client
        client = Client()
        if client.has_dataset(dataset_name=DATASET):
            client.delete_dataset(dataset_name=DATASET)
        ds = client.create_dataset(DATASET, description="SKU-days at the reorder point during a live disruption")
        client.create_examples(dataset_id=ds.id, inputs=[e["inputs"] for e in examples],
                               outputs=[e["outputs"] for e in examples])
        evaluators = [avoids_disrupted_supplier, protective_action, within_guardrails, has_rationale]
        for prefix, target in (("static-rop", static_target), ("supplygen-council", supplygen_target)):
            res = client.evaluate(target, data=DATASET, evaluators=evaluators, experiment_prefix=prefix,
                                  max_concurrency=4)
            print(f"LangSmith experiment: {res.experiment_name}")
        print("Open LangSmith > Datasets & Experiments > supplygen-reorder-moments, tick both experiments, Compare.")


if __name__ == "__main__":
    main()
