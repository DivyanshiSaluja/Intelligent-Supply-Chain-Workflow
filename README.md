# SupplyGen: signal-triaged multi-agent inventory and procurement workflow (proof of concept)

A daily loop watches stock for 30 SKUs, reads external signals (news, weather, festivals,
commodity prices), sends only the at-risk SKU-days to a LangGraph "Council of Agents",
passes the proposal through Supervisor guardrails and human approval, and logs every
decision with a readable rationale. It is benchmarked against three baselines (static
reorder point, moving-average reorder point, reactive dual sourcing) on a seeded synthetic
dataset and on real demand replayed from the public UCI Online Retail II dataset. A local
LLM (qwen3 via Ollama) can replace the rule-based Replenishment Planner.

## Project structure

```
Ecommerce_Supply_Workflow/
  supplygen/
    config.py        policy parameters, guardrail limits, paths
    db.py            SQLite schema (the warehouse) and master-data loader
    datagen.py       synthetic categories, suppliers, SKUs, 12 months of demand, memory
    scenarios.py     four stress scenarios, false-alarm signals, ground-truth effects
    simulation.py    day-by-day inventory simulation and metrics
    triage.py        signal-triage classifier
    agents.py        Signal Analyst, Memory-Recall, Demand Forecaster, Supplier Evaluator,
                     Replenishment Planner, Supervisor, human approval, audit logger
    graph.py         LangGraph wiring of the council
    controllers.py   Static ROP, Adaptive ROP, Reactive dual-source, SupplyGen
    realdata.py      real-demand dataset from UCI Online Retail II
    live_signals.py  Open-Meteo, Nager.Date / local festival calendar, GDELT, FRED
    llm.py           local qwen3 (Ollama): order planner, headline normaliser, briefings
  scripts/
    generate_data.py   build data/supplygen.db and data/csv/*.csv
    run_demo.py        one scenario end to end, prints the decision log
    run_benchmark.py   comparison + ablation + sensitivity -> results/
    make_figures.py    fig1..fig8 -> figures/
    make_diagrams.py   system architecture, flowchart, LangGraph Mermaid
    langsmith_eval.py  decision-level evaluation, optional LangSmith experiments
    llm_agent_study.py LLM planner vs rule-based planner on the same reorder moments
    prepare_real_data.py  build data/real_demand.db from the UCI dataset
    make_figures_extra.py fig9 to fig13 (LLM study, real demand, overall, protection, snapshot)
    make_traces.py     agent-by-agent execution traces from real runs
    live_monitor.py    real signals today -> triage -> council
  tests/test_supplygen.py
  paper/paper_sections.md   title, abstract, methodology, results tables, limitations
  data/  results/  figures/
```

## Run it (PowerShell, from the project folder)

```powershell
pip install -r requirements.txt

python scripts/generate_data.py                 # 1. synthetic dataset
python -m pytest -q                             # 2. nine tests
python scripts/run_demo.py --scenario supplier_failure --seed 0     # 3. one run + decision log
python scripts/run_benchmark.py --runs 30       # 4. full benchmark (about 5-10 min, 12 cores)
python scripts/make_figures.py                  # 5. eight result figures
python scripts/make_diagrams.py                 # 6. architecture + flowchart
python scripts/langsmith_eval.py                # 7. decision-level evaluation (local)

python scripts/prepare_real_data.py             # 8. real-demand dataset (uses the committed CSV)
python scripts/run_benchmark.py --dataset real  # 9. same benchmark on real demand -> results/real/
python scripts/llm_agent_study.py --seeds 3     # 10. LLM planner study (needs Ollama; 30-60 min on CPU)
python scripts/make_traces.py                   # 11. execution-trace tables -> results/execution_traces.md
python scripts/make_figures_extra.py            # 12. fig9 to fig13
```

Other modes:

```powershell
python scripts/run_demo.py --scenario commodity_shortage --interactive   # you approve / reject each escalation
python scripts/run_demo.py --scenario festival_surge --llm               # adds a qwen3 briefing (about 25 s each)
python scripts/live_monitor.py --stress 0.6                              # today's real signals, stock cut to 60%
python scripts/live_monitor.py --llm                                     # news headlines classified by qwen3
python scripts/run_benchmark.py --runs 5                                 # quick benchmark
```

Scenarios: `commodity_shortage`, `supplier_failure`, `weather_disruption`, `festival_surge`.

## Using LangSmith

1. Create a key at smith.langchain.com (Settings > API Keys).
2. Copy `.env.example` to `.env` and set `LANGSMITH_API_KEY`; keep `LANGSMITH_TRACING=true`.
3. **Traces:** `python scripts/run_demo.py --scenario supplier_failure`. Open the project
   `supplygen-poc` in LangSmith. Each council invocation is one trace named
   `council SKU-xxx day N`, tagged with the scenario and priority tier; the eight nodes show
   their JSON input and output, so any order can be traced back to the signal that caused it.
4. **Baseline comparison:** `python scripts/langsmith_eval.py --upload`. This creates the dataset
   `supplygen-reorder-moments` (90 SKU-days at the reorder point during a live disruption) and
   two experiments, `static-rop-*` and `supplygen-council-*`, scored by four evaluators
   (`avoids_disrupted_supplier`, `protective_action`, `within_guardrails`, `has_rationale`).
   In Datasets & Experiments, tick both experiments and press Compare.

The benchmark script turns tracing off on purpose (about 10,000 council calls per full run).
Both the tracing and the `--upload` path have been run against langsmith 0.8.

## Data

Two datasets share one schema.

- **Synthetic** (`data/supplygen.db`, readable copies in `data/csv/`): seeded with
  `MASTER_SEED = 42`, so every number is reproducible.
- **Real demand** (`data/real_demand.db`): daily units of the 30 most regularly sold products in
  UCI Online Retail II (Chen, 2019, CC BY 4.0, https://archive.ics.uci.edu/dataset/502/online+retail+ii),
  Dec 2009 to Dec 2011. The first 365 days are history; 120-day windows of the remaining 374 days
  are replayed. Only demand is real: the dataset has no suppliers, so the supplier layout and the
  injected disruptions are the same synthetic ones. `data/real/online_retail_ii_daily_top30.csv`
  is the derived file; the raw download is not committed.

Live signals are for demonstration only and are never used in a benchmark.

## Outputs

| File | Content |
|---|---|
| `results/summary.md` | Tables A to D (comparison, per scenario, operations, ablation and sensitivity) |
| `results/runs.csv` | one row per configuration, scenario and seed |
| `results/real/summary.md` | the same tables on real demand |
| `results/decision_eval.json` | decision-level evaluator scores |
| `results/llm_agent_study.json` | LLM planner: validity, agreement with rules, evaluator scores, latency |
| `figures/fig1..fig13*.png` | result figures |
| `results/execution_traces.md` | agent-by-agent reasoning logs for seven cases |
| `figures/system_architecture.png`, `workflow_flowchart.png`, `technology_stack.png`, `council_graph.mmd` | diagrams |
