"""LangGraph wiring of the Council of Agents."""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .agents import CouncilState, make_agents
from .config import Policy

COUNCIL_ORDER = ["signal_analyst", "memory_recall", "demand_forecaster",
                 "supplier_evaluator", "replenishment_planner", "supervisor"]


def build_graph(policy: Policy, episodes: list[dict], checkpointer=None, llm_planner: bool = False):
    """Compile the council. Pass a checkpointer to enable real human-in-the-loop interrupts."""
    nodes = make_agents(policy, episodes, llm_planner)
    g = StateGraph(CouncilState)
    for name, fn in nodes.items():
        g.add_node(name, fn)
    g.add_edge(START, COUNCIL_ORDER[0])
    for a, b in zip(COUNCIL_ORDER, COUNCIL_ORDER[1:]):
        g.add_edge(a, b)
    g.add_conditional_edges(
        "supervisor",
        lambda s: "human_approval" if s["verdict"].get("escalate") else "audit_logger",
        {"human_approval": "human_approval", "audit_logger": "audit_logger"})
    g.add_edge("human_approval", "audit_logger")
    g.add_edge("audit_logger", END)
    return g.compile(checkpointer=checkpointer)
