"""Run one scenario end to end and print the explainable decision log.

    python scripts/run_demo.py --scenario supplier_failure --seed 0
    python scripts/run_demo.py --scenario commodity_shortage --interactive   # you approve/reject
    python scripts/run_demo.py --scenario festival_surge --llm               # qwen3 briefing

Signals, daily stock and every council decision are written to data/supplygen.db
(tables disruption_events, inventory_state, decisions_log). With LANGSMITH_TRACING=true
every council invocation appears as a trace in LangSmith.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from langgraph.checkpoint.memory import MemorySaver

from supplygen.config import SCENARIOS, Policy
from supplygen.controllers import StaticROP, SupplyGen
from supplygen.db import connect, load_master
from supplygen.graph import build_graph
from supplygen.scenarios import public
from supplygen.simulation import Simulation


def ask_human(payload: dict) -> str:
    print("\n" + "=" * 78 + "\nHUMAN APPROVAL REQUIRED")
    for k, v in payload.items():
        print(f"  {k:14s} {v}")
    return input("  approve / reject > ") or "approve"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", choices=SCENARIOS, default="supplier_failure")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--show", type=int, default=4, help="decision records to print")
    ap.add_argument("--interactive", action="store_true", help="real human-in-the-loop prompts")
    ap.add_argument("--llm", action="store_true", help="add a local-LLM briefing to printed records")
    a = ap.parse_args()

    master, policy = load_master(), Policy()
    run_id = f"{a.scenario}-{a.seed}"
    sim = Simulation(master, a.scenario, a.seed, policy)
    decisions: list[dict] = []
    graph = build_graph(policy, master.episodes, MemorySaver()) if a.interactive else None
    agent = SupplyGen(policy, hitl_mode="interactive" if a.interactive else "auto", graph=graph,
                      on_decision=decisions.append, approver=ask_human)
    base = sim.run(StaticROP(policy))
    res = sim.run(agent)

    con = connect()
    for t in ("disruption_events", "inventory_state", "decisions_log"):
        con.execute(f"DELETE FROM {t} WHERE run_id = ?", (run_id,))
    for s in sim.signals:
        p = public(s)
        con.execute("INSERT INTO disruption_events (run_id, source, signal_type, published_day, start_day,"
                    " end_day, affected_supplier_id, affected_region, affected_commodity, affected_category_id,"
                    " severity_score, credibility, description) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (run_id, p["source"], p["signal_type"], p["published_day"], p["start_day"], p["end_day"],
                     p["affected_supplier_id"], p["affected_region"], p["affected_commodity"],
                     p["affected_category_id"], p["severity_score"], p["credibility"], p["description"]))
    for r in (base, res):
        con.executemany("INSERT INTO inventory_state VALUES (?,?,?,?,?,?,?,?)", [
            (run_id, r.controller, d, master.skus[i]["sku_id"], int(r.on_hand[d, i]), 0,
             int(r.demand[d, i]), int(r.unmet[d, i]))
            for d in range(r.on_hand.shape[0]) for i in range(len(master.skus))])
    con.executemany("INSERT INTO decisions_log (run_id, day, sku_id, action, qty, chosen_supplier_id,"
                    " supervisor_status, escalated, approved, erp_write_status, latency_ms, rationale_text)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
                        (run_id, d["day"], d["sku_id"], d["action"], d["qty"], d["chosen_supplier_id"],
                         d["supervisor_status"], int(d["escalated"]), int(d["approved"]),
                         d["erp_write_status"], round(d["latency_ms"], 3), d["rationale_text"]) for d in decisions])
    con.commit()

    true = sim.truth[0]
    print(f"\nScenario {a.scenario} (seed {a.seed}) - real disruption: days {true['start_day']}-{true['end_day']}, "
          f"severity {true['severity_score']}, published day {true['published_day']}")
    print(f"  \"{true['description']}\"\n")
    print(f"{'metric':28s}{'Static ROP':>14s}{'SupplyGen':>14s}")
    for k, lab in (("sbs", "Stockout Burden Score"), ("burden_pct", "Stockout burden %"), ("fill_rate", "Fill rate %"),
                   ("critical_availability", "Critical-SKU availability %"), ("critical_protection", "Critical protection %"),
                   ("total_cost", "Total cost"), ("avg_inventory_units", "Avg inventory (units)")):
        print(f"{lab:28s}{base.metrics[k]:14.2f}{res.metrics[k]:14.2f}")
    m = res.metrics
    print(f"\nCouncil invoked on {m['council_invocations']} of {agent.sku_days} SKU-days ({m['invocation_rate']:.2f}%), "
          f"mean latency {m['latency_ms_mean']:.2f} ms, {m['hitl_escalations']} human escalations, "
          f"{m['supplier_switches']} supplier switches.")

    shown = [d for d in decisions if d["action"] != "hold"][: a.show]
    print(f"\n--- First {len(shown)} council decision records (decisions_log.rationale_text) ---")
    for d in shown:
        print(f"\n[{d['action']} | qty {d['qty']} | supplier {d['chosen_supplier_id']} | {d['erp_write_status']} | "
              f"{d['latency_ms']:.2f} ms]\n{d['rationale_text']}")
        if a.llm:
            from supplygen.llm import narrate
            print(f"  LLM briefing: {narrate(d['rationale_text'])}")
    n = con.execute("SELECT COUNT(*) FROM decisions_log WHERE run_id = ?", (run_id,)).fetchone()[0]
    print(f"\n{n} decisions written to decisions_log (run_id '{run_id}').")
    con.close()


if __name__ == "__main__":
    main()
