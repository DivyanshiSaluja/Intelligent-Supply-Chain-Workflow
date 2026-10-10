# Handoff: drafting the SupplyGen paper

This page tells you what exists, which numbers to use, what the paper may claim, and what is
still missing. You do not need to run any code to write the draft.

## What the project is

SupplyGen is a prototype that watches stock for 30 products, reads external warning signals
(supplier shutdowns, commodity shortages, weather, festivals), and decides when and from whom to
reorder. A cheap screen ("triage") sends only the at-risk product-days to a group of five agents
built with LangGraph. A Supervisor applies limits and sends sensitive orders to a human. It is
compared with three simpler controllers in a simulation.

The motivation: shortages such as the edible-oil and food shortages during the Iran conflict
arrive with some warning in the news and in prices. A retailer that acts on those warnings can
protect its most important products before stock runs out.

## Where everything is

| You need | File |
|---|---|
| Title, keywords, abstract, methodology with 12 equations, 16 tables, discussion, limitations, conclusion | `paper/paper_sections.md` (start here) |
| Figures (13 result figures, architecture, flowchart, technology stack) | `figures/` |
| Result tables, synthetic demand | `results/summary.md` |
| Result tables, real demand | `results/real/summary.md` |
| Agent reasoning logs for seven cases | `results/execution_traces.md` |
| Language-model study | `results/llm_agent_study.json` |
| How to rerun anything | `README.md` |
| Writing rules from the guide | `Points.pdf` (ask Divyanshi) |
| Reference paper for structure | TrafficGen, Soni et al. 2026 (ask Divyanshi) |

`paper/paper_sections.md` lists which figure file is which figure number, and has a table
matching each element of the TrafficGen paper to its counterpart here.

## The numbers to use

120 runs per dataset (4 disruption scenarios x 30 repetitions). "Burden" is the Stockout Burden
Score: unmet units weighted 3, 2 or 1 by product priority.

| Result | Synthetic demand | Real demand (UCI Online Retail II) |
|---|---|---|
| Burden reduction vs static reorder point | 85.4% ± 7.2 | 50.1% ± 18.4 |
| Burden reduction vs reactive dual sourcing | 76.1% ± 14.0 | 32.1% ± 22.5 |
| Critical-product availability during disruption, static to SupplyGen | 62.0% to 99.8% | 86.4% to 99.5% |
| Share of product-days sent to the agents | 2.5% | 4.2% |
| Extra inventory held | +19.9% | +16.3% |
| Time per agent decision | 7.25 ms | 7.12 ms |

Language model as planner (qwen3:8b, 54 decisions): valid output 100%, never chose a disrupted
supplier, same supplier as the rule in 72.2% of cases, 22.5 s per decision. In all nine
festival cases it ordered far too little (median 44% of the rule's quantity).

## What the paper may claim

- Acting on warning signals protects critical products during disruptions: 99.5% availability
  on real demand, against 86.4% for the static policy and 90.0% for a static policy holding
  21% more stock.
- Lead with the real-demand figure (50.1%). The synthetic figure (85.4%) is an upper case.
- The Supplier Evaluator is the most valuable agent; triage keeps most of the benefit at a
  few percent of the agent calls.
- A hybrid design is supported: language model for reading signals and explaining decisions,
  rules for quantities, guardrails around both.

## What the paper must not claim

- **Not "LLM-based" results.** The 120-run benchmarks use rule-based agents. Only the
  54-decision study involves a language model.
- **Not a general cut in stockouts.** On real demand, simply holding 21% more stock gets a 42.4%
  reduction, close to SupplyGen's 50.1%. The advantage is specific to critical products
  during disruptions.
- **Not validated on a real disruption.** Demand is real in one dataset; suppliers, lead times
  and all disruptions are simulated.
- **Not connected to an ERP system.** Purchase orders are rows in a local database.
- **No targets were set in advance**, so do not write "exceeded the goal".

The full list of nine limitations is in `paper/paper_sections.md`; keep them in the paper.

## What is still missing (your work)

1. **Introduction**: background, why it matters, gap, contributions, paper outline. Not drafted.
2. **Literature review with a comparison table** (Study / Method / Dataset / Key result /
   Strength / Limitation), ending in the research gap. Not drafted.
3. **References**: at least 25, each checked on the publisher's page. None have been verified.
   The earlier draft's list has errors: it cites "Song et al. [1]" and "Calvanese et al. [2]"
   but entries [1] and [2] are by Dumas et al., and entry [4] has no authors.
4. **Citations for the Iran-conflict shortage** used as motivation, and for the UCI dataset.
5. **Table 9** has one row ("optimisation or learned policy") that describes an approach from
   the literature and needs citations.
6. Third person throughout, abbreviations spelled out at first use, every figure and table
   cited in the text, no citations in the abstract or conclusion (Points.pdf).

## If you change anything in the code

Rerun, in this order: `scripts/run_benchmark.py`, `scripts/run_benchmark.py --dataset real`,
`scripts/make_figures.py`, `scripts/make_traces.py`, `scripts/make_figures_extra.py`. Then
update the numbers in `paper/paper_sections.md` from the two `summary.md` files. Do not edit
numbers by hand.
