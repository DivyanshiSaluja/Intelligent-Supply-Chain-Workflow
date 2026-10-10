"""Live monitoring: fetch today's real signals and run triage + council on current stock.

    python scripts/live_monitor.py            # weather, holidays, news (keyword rules)
    python scripts/live_monitor.py --llm      # news headlines classified by local qwen3

'Current stock' is read from the latest inventory_state rows if a demo run exists,
otherwise from the policy's opening stock. Day 0 = today.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

import numpy as np

from supplygen.config import Policy
from supplygen.db import connect, load_master
from supplygen.graph import build_graph
from supplygen.live_signals import fetch_all
from supplygen.simulation import static_levels
from supplygen.triage import relevant_signals, triage


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--stress", type=float, default=1.0,
                    help="multiply current stock (e.g. 0.6) to see how the council reacts when stock is low")
    a = ap.parse_args()

    master, policy = load_master(), Policy()
    events, status = fetch_all(a.llm)
    print("Source status:")
    for k, v in status.items():
        print(f"  {k:9s} {v}")
    print(f"\n{len(events)} normalised live signals:")
    for e in events:
        print(f"  [{e['signal_type']:18s} sev {e['severity_score']:.2f} cred {e['credibility']:.2f}] {e['description'][:95]}")

    con = connect()
    con.execute("DELETE FROM disruption_events WHERE run_id = 'live'")
    con.executemany("INSERT INTO disruption_events (run_id, source, signal_type, published_day, start_day, end_day,"
                    " affected_supplier_id, affected_region, affected_commodity, affected_category_id, severity_score,"
                    " credibility, description) VALUES ('live',?,?,?,?,?,?,?,?,?,?,?,?)",
                    [(e["source"], e["signal_type"], e["published_day"], e["start_day"], e["end_day"],
                      e["affected_supplier_id"], e["affected_region"], e["affected_commodity"],
                      e["affected_category_id"], e["severity_score"], e["credibility"], e["description"]) for e in events])
    con.commit()

    rop, upto = static_levels(master, policy)
    stock = np.round(rop + 0.5 * (upto - rop))
    last = con.execute("SELECT sku_id, on_hand FROM inventory_state WHERE day = (SELECT MAX(day) FROM inventory_state)"
                       " AND controller = 'SupplyGen' GROUP BY sku_id").fetchall()
    if last:
        by = {r["sku_id"]: r["on_hand"] for r in last}
        stock = np.array([by.get(s["sku_id"], stock[i]) for i, s in enumerate(master.skus)], dtype=float)
    stock = stock * a.stress
    con.close()

    graph = build_graph(policy, master.episodes)
    flagged = 0
    print("\nTriage over all SKUs:")
    for i, sku in enumerate(master.skus):
        sups = [master.suppliers[s] for s in master.approved[sku["sku_id"]]]
        sigs = relevant_signals(events, sku, sups, 0, policy.lookahead_days)
        ctx = {"day": 0, "sku": sku, "suppliers": sups, "on_hand": int(stock[i]), "position": float(stock[i]),
               "mu": float(master.mu[i]), "sigma": float(master.sigma[i]), "rop": float(rop[i]),
               "recent_mean": float(master.history[-14:, i].mean()), "last_review_day": -99}
        if not sigs or not triage(ctx, sigs, policy)["flag"]:
            continue
        flagged += 1
        out = graph.invoke({"ctx": ctx, "signals": sigs, "hitl_mode": "auto"},
                           {"run_name": f"live council {sku['sku_code']}", "tags": ["live"]})
        print(f"\n  FLAGGED {sku['sku_code']}: {out['decision']['rationale_text']}")
    print(f"\n{flagged} of {len(master.skus)} SKUs routed to the council; the rest stay on the fast path.")


if __name__ == "__main__":
    main()
