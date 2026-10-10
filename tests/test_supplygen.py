"""Run with:  python -m pytest -q"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from supplygen.config import Policy
from supplygen.controllers import ReactiveDual, StaticROP, SupplyGen
from supplygen.datagen import generate
from supplygen.db import load_master
from supplygen.graph import build_graph
from supplygen.simulation import Simulation, static_levels
from supplygen.triage import triage

POLICY = Policy()


@pytest.fixture(scope="session")
def master(tmp_path_factory):
    db = tmp_path_factory.mktemp("db") / "test.db"
    generate(db)
    return load_master(db)


def ctx_for(master, i, day=40, position=None):
    rop, _ = static_levels(master, POLICY)
    sku = master.skus[i]
    return {"day": day, "sku": sku, "suppliers": [master.suppliers[s] for s in master.approved[sku["sku_id"]]],
            "on_hand": 0, "position": float(rop[i] * 0.9 if position is None else position),
            "mu": float(master.mu[i]), "sigma": float(master.sigma[i]), "rop": float(rop[i]),
            "recent_mean": float(master.mu[i]), "last_review_day": -99}


def failure_signal(supplier_id=1, sev=0.9, cred=0.95):
    return {"signal_id": 1, "source": "test", "signal_type": "supplier_failure", "published_day": 38,
            "start_day": 38, "end_day": 70, "affected_supplier_id": supplier_id, "affected_region": None,
            "affected_commodity": None, "affected_category_id": None, "severity_score": sev,
            "credibility": cred, "description": "test failure"}


def test_dataset_shape(master):
    assert len(master.skus) == 30 and len(master.suppliers) == 8 and len(master.categories) == 3
    assert master.history.shape == (365, 30)
    assert all(master.approved[s["sku_id"]][0] == s["primary_supplier_id"] for s in master.skus)


def test_runs_are_reproducible(master):
    a = Simulation(master, "supplier_failure", 3).run(SupplyGen(POLICY)).metrics["sbs"]
    b = Simulation(master, "supplier_failure", 3).run(SupplyGen(POLICY)).metrics["sbs"]
    assert a == b


def test_controllers_face_identical_demand(master):
    sim = Simulation(master, "festival_surge", 1)
    assert np.array_equal(sim.run(StaticROP(POLICY)).demand, sim.run(SupplyGen(POLICY)).demand)


def test_triage_ignores_low_credibility_rumour(master):
    assert not triage(ctx_for(master, 0), [failure_signal(sev=0.9, cred=0.3)], POLICY)["flag"]
    assert triage(ctx_for(master, 0), [failure_signal()], POLICY)["flag"]


def test_triage_threshold_one_equals_static_baseline(master):
    sim = Simulation(master, "commodity_shortage", 2)
    blind = sim.run(SupplyGen(POLICY.but(triage_threshold=1.01)))
    assert blind.metrics["sbs"] == sim.run(StaticROP(POLICY)).metrics["sbs"]
    assert blind.metrics["council_invocations"] == 0


def test_council_switches_away_from_failed_supplier(master):
    graph = build_graph(POLICY, master.episodes)
    out = graph.invoke({"ctx": ctx_for(master, 0), "signals": [failure_signal()], "hitl_mode": "auto"})
    d = out["decision"]
    assert d["action"] == "switch_supplier" and d["chosen_supplier_id"] != 1
    assert d["escalated"] and "Supervisor" in d["rationale_text"]      # critical SKU -> human


def test_supervisor_clips_oversized_order(master):
    graph = build_graph(POLICY.but(max_order_days=5), master.episodes)
    ctx = ctx_for(master, 0, position=0)
    out = graph.invoke({"ctx": ctx, "signals": [failure_signal()], "hitl_mode": "auto"})
    assert out["verdict"]["status"] == "clipped"
    assert out["decision"]["qty"] <= int(np.ceil(5 * ctx["mu"]))


def test_human_rejection_blocks_the_order(master):
    graph = build_graph(POLICY, master.episodes, MemorySaver())
    cfg = {"configurable": {"thread_id": "t1"}}
    paused = graph.invoke({"ctx": ctx_for(master, 0), "signals": [failure_signal()],
                           "hitl_mode": "interactive"}, cfg)
    assert "__interrupt__" in paused
    d = graph.invoke(Command(resume="reject"), cfg)["decision"]
    assert d["action"] == "hold" and d["erp_write_status"] == "po_rejected_by_human"


def test_supplygen_beats_static_under_supplier_failure(master):
    sim = Simulation(master, "supplier_failure", 0)
    assert sim.run(SupplyGen(POLICY)).metrics["sbs"] < 0.5 * sim.run(StaticROP(POLICY)).metrics["sbs"]


def test_reactive_baseline_sits_between_static_and_supplygen(master):
    sim = Simulation(master, "supplier_failure", 0)
    static, reactive, agent = (sim.run(c).metrics["sbs"] for c in (StaticROP(POLICY), ReactiveDual(POLICY), SupplyGen(POLICY)))
    assert agent < reactive < static


def test_reactive_baseline_equals_static_without_supply_problem(master):
    sim = Simulation(master, "festival_surge", 0)
    assert sim.run(ReactiveDual(POLICY)).metrics["sbs"] == sim.run(StaticROP(POLICY)).metrics["sbs"]
