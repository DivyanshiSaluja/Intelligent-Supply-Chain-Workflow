"""Optional local LLM (Ollama) used for language tasks only.

The numeric decision path is deterministic. The LLM (a) turns a raw news headline into
the normalised signal fields and (b) rewrites the audit record as an operator briefing.
Both fall back to deterministic output if the model is unavailable or returns bad JSON.
"""
from __future__ import annotations

import json
import os
import re
import time

import requests

MODEL = os.getenv("SUPPLYGEN_MODEL", "qwen3:8b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
SIGNAL_TYPES = ["commodity_shortage", "supplier_failure", "weather_disruption", "festival_surge", "irrelevant"]


def _chat(prompt: str, json_mode: bool = False) -> str:
    # Ollama's REST API is called directly so no extra Python client is required.
    body = {"model": MODEL, "stream": False, "think": False,
            "messages": [{"role": "user", "content": prompt}],
            "options": {"temperature": 0, "num_predict": 400}}
    if json_mode:
        body["format"] = "json"
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=180)
    r.raise_for_status()
    return re.sub(r"<think>.*?</think>", "", r.json()["message"]["content"], flags=re.S).strip()


def classify_headline(headline: str, commodities: list[str], regions: list[str]) -> dict:
    """Headline -> {signal_type, severity_score, affected_commodity, affected_region}."""
    prompt = (
        "You normalise supply-chain news for an e-commerce retailer that buys products depending on "
        f"these commodities: {commodities} (palm, sunflower and mustard oil all count as edible_oil; "
        "chips count as semiconductors). Return JSON only with keys:\n"
        "signal_type: commodity_shortage (price spike, export ban or scarcity of a commodity), "
        "supplier_failure (a named factory or supplier stops shipping), weather_disruption (storm, flood "
        "or similar blocking transport), festival_surge (holiday or sale raising demand), or irrelevant "
        "(none of these, or unrelated to the commodities).\n"
        "severity_score: 0 to 1, how badly supply or demand is affected.\n"
        f"affected_commodity: one of {commodities} or null.\n"
        f"affected_region: one of {regions} or null.\n"
        f"Headline: {headline}")
    try:
        out = json.loads(_chat(prompt, json_mode=True))
        if out.get("signal_type") not in SIGNAL_TYPES:
            raise ValueError("bad signal_type")
        out["severity_score"] = min(1.0, max(0.0, float(out.get("severity_score") or 0)))
        out["llm"] = MODEL
        return out
    except Exception as exc:   # deterministic fallback keeps ingestion running
        return {"signal_type": "irrelevant", "severity_score": 0.0, "affected_commodity": None,
                "affected_region": None, "llm": f"fallback ({type(exc).__name__})"}


def plan_order(facts: dict) -> dict:
    """Ask the LLM for supplier and quantity. Returns ok=False on any failure."""
    prompt = (
        "You are a procurement planner. Decide today's purchase order for one product.\n"
        "Rules: the order must cover demand from today until it arrives plus the usual days between "
        "orders, minus the stock position. Prefer the usual supplier unless it is currently disrupted "
        "or delivers much later than an alternative. If a supplier delivers only a share of what is "
        "ordered, order proportionally more. If stock already covers the need, order 0.\n"
        f"Facts (JSON): {json.dumps(facts)}\n"
        'Return JSON only: {"supplier_id": <int>, "qty": <int>, "reason": "<one sentence>"}')
    t0 = time.perf_counter()
    try:
        out = json.loads(_chat(prompt, json_mode=True))
        return {"ok": True, "supplier_id": int(out["supplier_id"]), "qty": int(float(out["qty"])),
                "reason": str(out.get("reason", ""))[:300], "latency_s": round(time.perf_counter() - t0, 2)}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "latency_s": round(time.perf_counter() - t0, 2)}


def narrate(rationale_text: str) -> str:
    """Rewrite the structured audit record as a short briefing for the approver."""
    prompt = ("Rewrite this procurement decision record as a 3-sentence briefing for a human "
              "approver. Keep every number exactly as given and add no new facts.\n\n" + rationale_text)
    try:
        return _chat(prompt)
    except Exception as exc:
        return f"[LLM unavailable: {type(exc).__name__}] {rationale_text}"
