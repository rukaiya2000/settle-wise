# SettleWise — Features to Implement

**Purpose:** interview demo for the Garrett Lab (UF Plant Pathology — network
science, R, advanced statistics, ML, safe LLM use). This file is the working
backlog: what to build, why it matters for *this* audience, where it lives, and
how much effort it is.

**The one thesis everything hangs off:**
> The LLM/analytics layer may *recommend*. Deterministic code decides anything
> that touches money or policy. Every visible feature is a window into a real
> method underneath.

**Two audiences, one demo:** the panel may lead non-technical, but it's a
network-science lab that ships R packages — assume at least one evaluator will
probe the methods. So: **visible, clickable features on the surface; genuine
network / statistics / ML underneath.** Nothing decorative that doesn't trace
back to the thesis.

**Language split:** Python runs the live SettleWise service (FastAPI + dashboard).
**R does all analysis** (network, statistics, ML) — `igraph`/`tidygraph`/`ggraph`,
`tidymodels`, `survival`. The two meet at `data/settlewise.db`.

---

## Priority legend

- **P0** — build first; cheap, fully specified, high demo value.
- **P1** — the substance the JD screens for (network + stats + ML in R).
- **P2** — stretch / texture if time allows.
- **R?** — needs the R analytical layer.

---

## Track A — Operational dashboard features (small, showable, non-technical friendly)

These are quick wins that make the system legible in a live demo. Mostly
front-end; little or no schema change.

### A1. "Needs human review" queue  — P0 · R? no
A visible inbox at the top of the Borrowers view collecting every
`needs_review` case: borrower name, escalation reason, when, and a "Open /
Call back" action, with a count badge.
- **Why it lands:** shows the recommend-vs-execute safety boundary in one glance.
- **Where:** `dashboard/index.html`, `dashboard/app.js`, `dashboard/styles.css`.
- **Backend:** none — `/api/debts` already returns `status` + `last_call_summary`;
  pure front-end filter on `status === "needs_review"`.
- **Effort:** ~30 min.

### A2. "I don't want to talk to a robot" → escalate  — P0 · R? no
Explicit agent trigger: borrower refuses the automated agent / asks for a real
person → agree warmly, `mark_needs_review` with reason `"requested human agent"`,
close. Distinct reason string so it's identifiable in the A1 queue.
- **Why it lands:** the exact scenario a non-technical viewer will test live.
- **Where:** `server/agent/prompt.md` (add a line near the existing
  "ask for a human/manager" case at ~L260). Tool `mark_needs_review` already exists.
- **Effort:** ~10 min.

### A3. "Next best action" card on the borrower page  — P1 · R? yes (stub first)
A plain-language card: recommended action (Call / SMS / Human review),
preferred contact window, predicted payment probability, behavior segment.
- **Why it lands:** turns the ML prediction into something a non-technical
  person reads instantly; a technical person can ask how the number was made.
- **Where:** `dashboard/index.html`, `dashboard/app.js`; served by a new
  `GET /api/intelligence/borrowers/{debt_id}` (Python route reading R output).
- **Ship in two steps:** (1) static stub card wired to the page; (2) real values
  from the R layer (B3).
- **Effort:** stub ~30 min; real values gated on B3.

### A4. "Borrowers like this one" panel  — P1 · R? yes
On the borrower page, list the k nearest historical borrowers by behavior, each
with their outcome ("paid after evening contact", etc.).
- **Why it lands:** this *is* network analysis, shown to a non-technical viewer
  as "similar people." Directly echoes the lab's cohort thinking.
- **Where:** `dashboard/*`; served by `GET /api/intelligence/borrowers/{debt_id}/neighbors`
  reading the k-NN graph from the R layer (B1).
- **Effort:** UI ~30 min; depends on B1.

### A5. "Why" evidence list  — P1 · R? yes
Under the recommendation, 2–4 plain bullets citing the evidence
(prediction, statistical finding, similar cohort) with IDs.
- **Why it lands:** explainability + your statistics, made human-readable.
- **Where:** `dashboard/*`, same intelligence endpoint as A3.
- **Effort:** ~20 min once B2/B3 exist.

### A6. Segment badge  — P2 · R? yes
Small colored label on each borrower ("Delayed but Responsive") = the
community-detection output as a plain word.
- **Where:** `dashboard/*`, from B1 output.
- **Effort:** ~15 min.

---

## Track B — Intelligence layer in R (the substance the JD screens for)

This is where the network / statistics / ML depth lives. Reads
`data/settlewise.db`, writes analytical outputs the Python API serves to Track A.

### B0. Seedable synthetic data generator  — P1 · R? yes
Generate a realistic population (~1,000 borrowers, 8–12 weeks of events) with
**hidden ground-truth** structure: behavioral clusters, a time-of-day effect, a
reminder-after-promise effect — **plus one deliberately null effect**.
- **Why it matters:** lets you *validate* that methods recover known structure,
  and show your method correctly finds nothing in the null. Strongest possible
  credibility signal to a stats panel.
- **Effort:** medium.

### B1. Behavioral similarity network  — P1 · R? yes
Nodes = borrowers; edges = k-NN cosine similarity of behavior vectors.
- Louvain communities (= segments), **betweenness to find "bridge" borrowers**,
  degree/eigenvector centrality, nearest-neighbor cohort retrieval (feeds A4).
- **Validate:** modularity + **Adjusted Rand Index** vs. planted segments;
  a configuration-model null to show structure isn't random.
- **Tools:** `igraph`, `tidygraph`, `ggraph`.
- **Defense against "isn't this just clustering?":** retrieval + betweenness +
  null model. (Have this answer ready.)

### B2. Statistical analyses  — P1 · R? yes
Tie statistics to the network so it validates the segments, not a side demo:
- Communities × outcome: chi-square (Cramér's V) — *do the segments differ?*
- Bootstrap CIs on segment payment rates.
- **Kaplan–Meier + Cox** survival on time-to-payment by segment (the marquee
  "advanced statistics" flex; R's home turf).
- Contact-time and reminder-effect analyses (both planted in B0).
- **Benjamini–Hochberg** correction across tests, incl. the planted null.
- **Reporting rule:** every finding shows sample size, method, effect size,
  uncertainty, limitations — never a bare p-value.

### B3. Right-sized ML  — P1 · R? yes
Predict payment-after-contact:
- Baseline = historical rate → penalized logistic (`glmnet`) → one `xgboost`.
- **Time-aware split** (`rsample`), ROC/PR, **calibration** (`probably`).
- Inputs include graph-derived features (community id, neighbor payment rate) —
  links network → ML.
- Deliberately small and honest; quote the requirements doc: *ML must solve an
  explicit prediction problem, not showcase technology.*

### B4. Scenario / prioritization layer  — P2 · R? yes
The Garrett-lab analog: with limited agent capacity, which borrowers/cohorts to
contact first to maximize collected amount? Rank by centrality × predicted
probability; compare targeting strategies vs. naive ("collections captured",
analogous to `smartsurv` "outbreak averted"). Optional: state-transition network
+ intervention scenario analysis (INA-flavored).

---

## Track C — Presentation & reproducibility

### C1. Quarto report  — P1 · R? yes
The R analysis rendered as a Quarto doc (code + `ggraph` figure + KM curves +
calibration plot + narrative). Doubles as the presentation and hits the
communication bullet.

### C2. Reproducible pipeline  — P1 · R? yes
`renv` for the R environment; a `targets` pipeline so the whole analysis rebuilds
from a seed. Signals you work like a collaborator, not a lone notebook.

### C3. Intelligence API namespace  — P1 · R? no (serves R output)
`GET /api/intelligence/borrowers/{debt_id}` (feature snapshot, prediction,
segment, neighbors, evidence). Thin Python route reading the R layer's outputs.

---

## Feature → JD skill map

| Feature | R | Network | Stats | ML | Safe LLM | Software | Communication |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| A1 Human-review queue |  |  |  |  | ✓ | ✓ | ✓ |
| A2 "No robot" escalation |  |  |  |  | ✓ | ✓ |  |
| A3 Next-best-action card | ✓ |  |  | ✓ |  | ✓ | ✓ |
| A4 Similar-borrowers panel | ✓ | ✓ |  |  |  | ✓ | ✓ |
| A5 Why / evidence list | ✓ |  | ✓ |  | ✓ |  | ✓ |
| B1 Similarity network | ✓ | ✓ |  |  |  |  |  |
| B2 Statistics | ✓ | ✓ | ✓ |  |  |  |  |
| B3 ML | ✓ | ✓ |  | ✓ |  |  |  |
| B4 Scenario / prioritization | ✓ | ✓ | ✓ | ✓ |  |  |  |
| C1 Quarto report | ✓ |  |  |  |  |  | ✓ |
| C2 renv + targets | ✓ |  |  |  |  | ✓ |  |

---

## Suggested build order

1. **A1 + A2** — visible, fully spec'd, ~40 min total. Something to click.
2. **B0** — synthetic data with hidden ground truth + a null.
3. **B1** — the network (communities, bridges, retrieval) + ARI validation.
4. **A4 + A6** — surface the network as "similar people" and segment badges.
5. **B2** — statistics that validate the segments (survival = headline).
6. **B3 + A3 + A5** — the model, then the next-best-action card and evidence.
7. **C1 + C2 + C3** — Quarto report, reproducible pipeline, API glue.
8. **B4** — scenario / prioritization if time remains.

## Demo script (2 minutes)
1. Click a borrower → **Next best action** card + **similar borrowers** + **why**.
2. Run the agent; borrower says *"I don't want a robot"* → watch it appear in the
   **human-review queue**.
3. Open the **Quarto report**: the `ggraph` network, community validation (ARI),
   the survival curve, the calibrated model. State plainly: recommendations are
   evidence; the offer engine still decides money.

---

## Scope discipline (from the requirements doc, §26)
Do **not** ship a collection of unrelated AI demos. Cut for now: orchestrator,
critic agent, tree-model zoo, embeddings/PageRank, the 5-arm experiment. Every
feature above traces back to the one thesis.
