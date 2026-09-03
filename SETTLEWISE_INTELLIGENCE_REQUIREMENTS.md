# SettleWise Intelligence — Updated Product & Technical Requirements

**Document status:** Proposed extension of the existing SettleWise codebase  
**Target:** SettleWise 2.0 / Intelligence Layer  
**Primary goal:** Extend the existing AI collections agent into a data-driven, multi-agent collections intelligence platform without weakening the existing deterministic safety and policy controls.

---

## 1. Executive Summary

SettleWise currently provides an AI collections agent that can contact borrowers, verify identity, retrieve the amount due, negotiate within policy limits, send a payment link, store useful memory, schedule follow-ups, and escalate uncertain or sensitive cases to a human. The core architectural principle is that financial figures, offers, and state changes come from backend tools and deterministic code rather than from an LLM's judgment.

The next version will add an **Intelligence Layer** on top of this foundation.

The Intelligence Layer will analyze historical collection activity, borrower behavior, call outcomes, payment behavior, agent actions, and campaign-level patterns. It will use specialized agents and deterministic analytics tools to produce evidence-backed recommendations for the existing collections workflow.

The system will support:

- Multi-agent analysis and orchestration
- Historical collection analytics
- Statistical inference and hypothesis testing
- Predictive modeling where a real prediction problem exists
- Behavioral clustering and similarity analysis
- Temporal analysis and forecasting
- Graph/network analysis of borrower, behavior, event, and campaign relationships
- Personalized pre-call strategy recommendations
- Post-call outcome analysis
- Explainable recommendations with supporting evidence
- Evaluation of whether recommendations improve collection outcomes
- Strict separation between **AI recommendations** and **policy-authorized actions**

The system must remain safe by design:

> **The AI may recommend. Deterministic services decide what may actually be executed.**

---

# 2. Product Vision

## 2.1 Current SettleWise

```text
Borrower
   ↓
Voice / Conversation Agent
   ↓
Tool Calls
   ↓
Database + Policy + Offer Engine
   ↓
Negotiation
   ↓
Payment / Follow-up / Escalation
```

## 2.2 SettleWise 2.0

```text
                     Historical + Live Data
                              │
                              ▼
                    Intelligence Data Layer
                              │
             ┌────────────────┼─────────────────┐
             ▼                ▼                 ▼
       Analytics Agent    ML Agent       Network Agent
             │                │                 │
             ▼                ▼                 ▼
       Statistics       Prediction        Graph Analysis
             │                │                 │
             └────────────────┼─────────────────┘
                              ▼
                       Strategy Agent
                              │
                              ▼
                  Evidence-backed Call Plan
                              │
                              ▼
                    Existing Voice Agent
                              │
                              ▼
                    Policy / Offer Engine
                              │
                   ┌──────────┴──────────┐
                   ▼                     ▼
                Execute               Escalate
                   │
                   ▼
                Outcomes
                   │
                   ▼
             Analytics / Evaluation
```

---

# 3. Objectives

## O1 — Personalize collection strategy

Before a collection attempt, generate an evidence-backed recommendation for:

- whether outreach should occur now
- preferred outreach window
- recommended communication style
- expected probability of successful payment
- likely borrower response pattern
- recommended negotiation starting point, subject to the existing policy engine
- whether the case should be routed directly to human review

## O2 — Understand collection behavior

Analyze historical activity to identify:

- successful and unsuccessful contact patterns
- payment behavior
- repeated objections
- timing effects
- installment preferences
- follow-up effectiveness
- behavioral segments
- campaign-level bottlenecks

## O3 — Support rigorous statistical analysis

The system must distinguish descriptive patterns from statistically supported findings.

Examples:

- Does contact time affect payment probability?
- Does a reminder after a promise-to-pay improve completion?
- Does a particular negotiation strategy correlate with successful payment?
- Are apparent differences between borrower groups statistically significant?
- How much uncertainty exists in each estimate?

## O4 — Introduce predictive ML only where justified

ML must solve an explicit prediction or ranking problem. The system must not add a model simply for technology showcase purposes.

Initial prediction targets may include:

- probability of successful payment after contact
- probability of promise-to-pay completion
- likelihood of requiring human review
- expected time to payment
- risk of repeated unsuccessful contact

## O5 — Add meaningful network analysis

Network analysis must expose relationships that are difficult to detect from flat tables.

The first graph should focus on **behavioral and event similarity**, not on inventing social relationships between borrowers.

Possible graph relationships:

- borrower → behavior pattern
- borrower → objection type
- borrower → contact time bucket
- borrower → payment outcome
- borrower → strategy used
- borrower → event sequence
- borrower ↔ behavior similarity
- strategy → outcome
- time window → outcome

The system may later support operational or organizational relationship graphs if such data exists.

## O6 — Close the feedback loop

Every recommendation should eventually be connected to an observed outcome so SettleWise can evaluate:

```text
Recommendation → Action → Outcome → Evaluation
```

---

# 4. Scope

## 4.1 In scope

- New intelligence service/module
- Analytics data pipeline
- Feature generation
- Statistical analysis service
- Optional ML prediction service
- Graph construction and graph analytics
- Strategy recommendation agent
- Critic/validation agent
- Evidence records for recommendations
- Intelligence dashboard
- Model and recommendation evaluation
- Synthetic historical dataset generation
- Integration with existing borrower/debt/call/payment/memory data
- API endpoints for analytics and recommendations
- Background jobs for feature refresh and analysis

## 4.2 Out of scope for initial version

- Autonomous modification of policy limits
- Autonomous approval of offers outside the current offer engine
- Autonomous legal/compliance interpretation
- Real-world credit underwriting
- Real-world adverse-action decisions
- Fully autonomous collection policy optimization
- Training a large language model from scratch
- Replacing the deterministic offer engine
- Treating graph centrality as a creditworthiness score

---

# 5. Core Design Principle

## 5.1 Recommendation vs. execution

The architecture must have two clearly separated layers.

### Intelligence layer

May:

- analyze data
- generate hypotheses
- estimate probabilities
- recommend strategies
- rank options
- explain evidence
- identify anomalies

### Execution layer

Must remain deterministic and authoritative for:

- allowed contact times
- identity verification requirements
- payment amounts
- discount caps
- payment floors
- installment limits
- payment link generation
- status changes
- human escalation

The LLM must never bypass execution-layer controls.

---

# 6. Multi-Agent Architecture

## 6.1 Orchestrator Agent

Responsible for routing an investigation or strategy task to the required specialist agents.

Example request:

> "Prepare the best collection strategy for borrower debt_002."

The orchestrator should decide whether to invoke:

- Data Agent
- Statistics Agent
- Prediction Agent
- Network Agent
- Strategy Agent
- Critic Agent

The orchestrator must not directly mutate financial state.

## 6.2 Data Analyst Agent

Responsibilities:

- inspect available datasets
- determine required fields
- detect missing or invalid data
- summarize historical behavior
- generate analytical datasets
- identify whether enough data exists for a requested analysis

The agent calls deterministic Python/data tools for actual calculations.

## 6.3 Statistics Agent

Responsibilities:

- formulate testable hypotheses
- select appropriate statistical methods
- run deterministic statistical tools
- report effect sizes
- report confidence intervals or credible intervals
- report p-values where appropriate
- flag insufficient sample sizes
- distinguish correlation from causation

Potential methods:

- descriptive statistics
- confidence intervals
- two-sample tests
- chi-square tests
- Mann–Whitney U
- correlation analysis
- logistic regression
- generalized linear models
- survival analysis
- Kaplan–Meier estimates
- time-series decomposition
- bootstrap confidence intervals
- Bayesian estimation for selected analyses

The agent must return structured evidence rather than free-form claims.

## 6.4 Prediction Agent

Responsibilities:

- prepare model features
- train approved baseline models
- evaluate models using time-aware splits where appropriate
- produce calibrated probabilities when feasible
- return prediction plus uncertainty/quality metadata
- monitor model drift

Candidate models:

1. Logistic Regression — interpretable baseline
2. Random Forest — nonlinear baseline
3. Gradient Boosting / XGBoost — performance model
4. Survival model — time-to-payment use case

No model is considered mandatory. A simple statistical baseline should be implemented first.

## 6.5 Network Agent

Responsibilities:

- build behavioral/event graphs
- calculate graph metrics
- identify communities
- identify similar borrower cohorts
- surface repeated patterns across events
- explain why a graph relationship matters

Candidate techniques:

- degree centrality
- betweenness centrality
- PageRank where appropriate
- connected components
- Louvain / Leiden community detection
- cosine or feature similarity edges
- k-nearest-neighbor behavioral graph
- temporal graph analysis

The graph must not be used to infer sensitive or unsupported borrower relationships.

## 6.6 Strategy Agent

Converts analytical findings into a structured pre-call recommendation.

Example output:

```json
{
  "debt_id": "debt_002",
  "recommended_contact_window": "18:00-20:00",
  "predicted_payment_probability": 0.72,
  "behavior_segment": "delayed_but_responsive",
  "recommended_style": "direct_and_flexible",
  "recommended_next_action": "call",
  "human_review_recommended": false,
  "evidence_ids": ["stat_104", "model_022", "graph_311"]
}
```

The recommendation must never contain an unauthorized payment amount as an executable action. Any monetary proposal must be validated through the existing offer engine.

## 6.7 Critic Agent

Reviews recommendations for:

- unsupported claims
- insufficient evidence
- statistical mistakes
- data leakage
- overconfident predictions
- correlation/causation errors
- policy violations
- contradictions between agents
- stale features

The critic should return:

```text
PASS
or
REVIEW_REQUIRED
```

with structured reasons.

---

# 7. Data Requirements

## 7.1 Existing source entities

The intelligence layer should integrate with existing SettleWise entities, including:

- debts
- calls
- SMS events
- payments
- memory
- policies
- demo clock / time progression
- agent actions / tool traces where available

The existing project already uses a deterministic demo clock and synthetic activity replay. The intelligence layer should leverage this instead of introducing a separate time model.

## 7.2 New analytical entities

Add an analytics-oriented representation rather than overloading the operational tables.

Suggested entities:

### `interaction_events`

Fields:

- `event_id`
- `debt_id`
- `event_time`
- `event_type`
- `channel`
- `outcome`
- `strategy_id`
- `amount_due_at_event`
- `amount_offered`
- `amount_paid`
- `response_time_seconds`
- `metadata_json`

### `borrower_features`

Fields:

- `debt_id`
- `as_of_time`
- `contact_success_rate`
- `payment_success_rate`
- `promise_completion_rate`
- `days_since_last_payment`
- `days_since_last_contact`
- `average_response_time`
- `preferred_contact_hour`
- `objection_frequency`
- `historical_offer_acceptance_rate`
- `feature_version`

### `predictions`

Fields:

- `prediction_id`
- `debt_id`
- `prediction_type`
- `prediction_value`
- `model_version`
- `generated_at`
- `feature_version`
- `confidence_metadata_json`

### `statistical_findings`

Fields:

- `finding_id`
- `analysis_name`
- `hypothesis`
- `method`
- `sample_size`
- `effect_size`
- `p_value`
- `confidence_interval_json`
- `result_summary`
- `created_at`

### `graph_snapshots`

Fields:

- `graph_id`
- `snapshot_time`
- `node_count`
- `edge_count`
- `construction_method`
- `graph_version`

### `recommendations`

Fields:

- `recommendation_id`
- `debt_id`
- `generated_at`
- `recommendation_type`
- `recommendation_json`
- `critic_status`
- `evidence_ids`
- `executed_action`
- `observed_outcome`

---

# 8. Data Pipeline Requirements

The data pipeline must transform operational data into analysis-ready datasets.

```text
SQLite / operational tables
        ↓
Event extraction
        ↓
Data validation
        ↓
Feature engineering
        ↓
Feature snapshots
        ↓
Statistics / ML / Graph analysis
        ↓
Evidence store
        ↓
Strategy recommendations
```

## 8.1 Data quality checks

The pipeline must validate:

- missing values
- duplicate events
- impossible payment amounts
- negative balances
- invalid timestamps
- inconsistent event ordering
- future-dated events
- impossible status transitions
- leakage from future outcomes into past features

## 8.2 Reproducibility

Every analysis must record:

- dataset version
- feature version
- analysis version
- model version if applicable
- demo-clock timestamp / as-of time
- random seed where randomness exists

---

# 9. Statistical Analysis Requirements

## 9.1 Required initial analyses

### A. Contact-time effect

Question:

> Does contact time affect the probability of successful payment?

Potential analysis:

- group comparison
- logistic regression with time bucket
- confidence intervals
- effect size

### B. Reminder effectiveness

Question:

> Does a reminder after a promise-to-pay increase completion probability?

Potential analysis:

- matched cohort or observational comparison
- logistic regression
- sensitivity analysis

### C. Negotiation outcome analysis

Question:

> Are certain negotiation patterns associated with successful repayment?

Potential analysis:

- stratified analysis
- regression
- effect size
- confounder controls

### D. Time-to-payment analysis

Question:

> How long does a successful payment typically take after outreach?

Potential analysis:

- Kaplan–Meier survival curve
- median time-to-event
- cohort comparison

## 9.2 Statistical reporting

Every statistical finding must expose:

- sample size
- method
- effect size
- uncertainty
- statistical significance where applicable
- assumptions
- limitations

The UI must not display a p-value without context.

---

# 10. Machine Learning Requirements

## 10.1 Primary task

Implement one meaningful baseline prediction task first:

> Predict the probability that a borrower will make a successful payment after the next collection attempt.

## 10.2 Baselines

The first evaluation must compare:

1. simple historical-rate baseline
2. logistic regression
3. tree-based model

## 10.3 Evaluation

Required metrics:

- ROC-AUC
- PR-AUC
- precision
- recall
- F1
- Brier score
- calibration curve
- confusion matrix at a selected operating threshold

Class imbalance must be explicitly measured and addressed.

## 10.4 Temporal validation

Training features must only use information available **before** the prediction timestamp.

Use chronological train/validation/test splits rather than random splits when historical ordering matters.

## 10.5 Explainability

For each prediction, expose a concise explanation based on model features, for example:

```text
Prediction: 0.72 payment probability

Major contributing historical factors:
+ High prior contact response rate
+ Recent successful promise-to-pay
- Long gap since last payment
```

The explanation must reflect actual model/features and must not be fabricated by the LLM.

---

# 11. Network Analysis Requirements

## 11.1 Initial graph model

Use a **behavioral similarity graph**.

Each borrower is represented using a feature vector derived from historical interactions.

Create an edge between borrowers when their behavior is sufficiently similar.

Example:

```text
Borrower A ───── Borrower C
     │             │
     │             │
Borrower B ───── Borrower D
```

Nodes can additionally carry:

- behavior segment
- payment outcome statistics
- preferred contact time
- historical interaction counts

## 11.2 Edge construction

Possible approaches:

- cosine similarity
- k-nearest neighbors
- shared behavior-pattern count

The edge definition must be deterministic and documented.

## 11.3 Network analyses

Required initial analyses:

- connected components
- community detection
- node degree
- similarity ranking

Optional advanced analyses:

- betweenness centrality
- PageRank
- temporal community changes
- graph embeddings

## 11.4 Network use in recommendations

Network information may be used to identify similar historical cohorts.

Example:

> "This borrower is most similar to a historical cohort whose successful payments were more frequent after evening contact."

Network analysis must not independently determine a borrower’s eligibility, penalties, or financial terms.

---

# 12. Recommendation Workflow

## 12.1 Pre-call workflow

```text
1. Call request created
2. Load operational borrower/debt data
3. Load feature snapshot
4. Run prediction if current
5. Query relevant statistical findings
6. Query behavioral graph cohort
7. Strategy Agent produces recommendation
8. Critic Agent validates recommendation
9. Policy service verifies executable constraints
10. Existing voice agent starts call
```

## 12.2 During-call workflow

The existing voice agent remains the primary borrower-facing agent.

New intelligence capabilities may provide read-only context such as:

- preferred contact time
- previous objections
- likely response pattern
- recommended conversation style
- whether human review is advised

The voice agent must still use the existing tool-first rules for all debt and payment information.

## 12.3 Post-call workflow

```text
Call ends
  ↓
Extract structured outcome
  ↓
Update operational tables
  ↓
Write interaction event
  ↓
Refresh borrower features
  ↓
Record recommendation outcome
  ↓
Evaluate prediction
  ↓
Update analytics
```

---

# 13. Intelligence Dashboard Requirements

Add a new **Intelligence** section to the current dashboard.

## 13.1 Portfolio overview

Display:

- total outstanding balance
- collection rate
- payment conversion rate
- promise-to-pay completion rate
- contact success rate
- average days to payment
- human escalation rate
- strategy performance

## 13.2 Borrower intelligence page

For a selected borrower show:

```text
Borrower Intelligence
──────────────────────
Payment Probability       72%
Behavior Segment          Delayed but Responsive
Preferred Contact Time   6 PM – 8 PM
Contact Success Rate     68%
Promise Completion       75%

Recommended Action       Call
Recommended Style        Direct + Flexible
Human Review              No

Evidence
- Prediction #...
- Statistical finding #...
- Similar cohort #...
```

## 13.3 Network view

Visualize the behavioral similarity graph.

Capabilities:

- zoom/pan
- inspect node
- inspect similar borrowers
- highlight community
- show selected borrower’s nearest neighbors
- display relationship definition

## 13.4 Statistical insights view

Show findings with:

- question
- method
- sample size
- effect size
- uncertainty
- interpretation
- limitations

## 13.5 Strategy evaluation

Show:

```text
Strategy                  Attempts  Payment Rate  Avg Days
-----------------------------------------------------------
Standard                   120       31%           5.8
Reminder-first              95       39%           4.9
Evening-contact             80       46%           4.3
Human-review               25       52%           3.8
```

These values must come from actual system data, not hard-coded UI examples.

---

# 14. API Requirements

Add an intelligence API namespace, for example `/api/intelligence`.

## Required endpoints

### `GET /api/intelligence/borrowers/{debt_id}`

Returns:

- feature snapshot
- prediction
- behavior segment
- latest recommendation
- supporting findings

### `POST /api/intelligence/analyze/{debt_id}`

Runs an on-demand analysis for one borrower.

### `POST /api/intelligence/recommend/{debt_id}`

Generates a new strategy recommendation.

### `GET /api/intelligence/statistics`

Returns portfolio-level statistical findings.

### `GET /api/intelligence/network`

Returns graph metadata and nodes/edges for visualization.

### `GET /api/intelligence/strategies`

Returns strategy-level performance metrics.

### `GET /api/intelligence/models`

Returns model versions and evaluation metrics.

### `GET /api/intelligence/recommendations/{recommendation_id}`

Returns recommendation, evidence, critic decision, and observed outcome.

---

# 15. Agent Tool Requirements

The intelligence agents must use explicit deterministic tools.

Suggested tools:

- `get_historical_interactions(debt_id)`
- `get_feature_snapshot(debt_id)`
- `get_payment_history(debt_id)`
- `get_behavior_similarities(debt_id)`
- `run_statistical_test(analysis_id, parameters)`
- `get_statistical_finding(finding_id)`
- `predict_payment_probability(debt_id)`
- `get_model_explanation(prediction_id)`
- `get_network_neighbors(debt_id)`
- `get_network_metrics(debt_id)`
- `get_strategy_performance(strategy_id)`
- `create_strategy_recommendation(payload)`
- `criticize_recommendation(recommendation_id)`

The agents must not receive unrestricted database access.

---

# 16. LLM/API Requirements

The project may use an LLM API key for reasoning and orchestration.

The LLM is responsible for:

- deciding which analytical tools to invoke
- turning user questions into analytical plans
- synthesizing structured findings
- generating explanations
- producing strategy recommendations
- challenging assumptions through the critic role

The LLM is **not** responsible for:

- computing financial amounts
- determining payment floors
- executing offers
- calculating statistical results itself
- generating model metrics from memory
- overriding policy
- directly mutating operational database state

All numerical analysis should be executed by deterministic code and returned to the LLM as structured tool results.

---

# 17. Safety, Governance, and Auditability

## 17.1 Immutable evidence trail

Every recommendation should be traceable to:

```text
Recommendation
    ↓
Evidence IDs
    ↓
Data snapshot
    ↓
Analysis / model version
    ↓
Source events
```

## 17.2 Policy boundary

No intelligence component may:

- lower a payment floor
- exceed a discount cap
- invent an installment plan
- approve a disputed debt
- bypass identity verification
- suppress a required human escalation

## 17.3 Sensitive-data minimization

Do not use sensitive borrower information as a graph relationship or predictive feature unless explicitly justified, permitted, and reviewed.

## 17.4 Human review

Human review must remain available for:

- disputes
- identity problems
- fraud reports
- severe distress/vulnerability
- policy exceptions
- low confidence
- system/data quality anomalies

---

# 18. Evaluation Framework

The upgraded system should be evaluated at four levels.

## 18.1 Agent evaluation

Measure:

- correct tool selection
- tool-call validity
- unsupported-claim rate
- policy violation rate
- escalation correctness

## 18.2 Statistical evaluation

Measure:

- test validity
- confidence interval correctness
- false discovery risk when many hypotheses are tested
- reproducibility

## 18.3 ML evaluation

Measure:

- predictive quality
- calibration
- temporal generalization
- subgroup stability
- drift over time

## 18.4 Business/workflow evaluation

Compare:

### Baseline
Existing SettleWise strategy.

### Enhanced
Existing SettleWise + Intelligence recommendations.

Metrics:

- payment conversion
- payment amount collected
- time to payment
- successful-contact rate
- promise-to-pay completion
- human escalation rate
- average number of attempts

Because this is a synthetic/demo environment, results must be described as **simulated evaluation results** rather than real-world collection performance.

---

# 19. Experimental Design

A strong research-style evaluation should compare:

```text
A. Rule-based baseline
B. LLM strategy only
C. LLM + statistical analysis
D. LLM + ML prediction
E. LLM + statistics + ML + network analysis
```

Primary question:

> Does adding evidence-backed analytics improve recommendation quality and simulated collection outcomes compared with an agent that reasons without the intelligence layer?

Secondary questions:

1. Does statistical evidence reduce unsupported recommendations?
2. Does predictive modeling improve ranking of outreach candidates?
3. Does behavioral network information improve strategy selection?
4. Does the critic reduce policy or reasoning errors?

---

# 20. Synthetic Data Requirements

Because this project is currently a controlled/demo system, it should include a reproducible synthetic data generator.

The generator should produce:

- borrowers/debts
- call events
- payment events
- SMS events
- promise-to-pay events
- objections
- contact outcomes
- time-of-day effects
- behavioral clusters
- strategy assignments

The generator must support known ground-truth relationships so analytical methods can be tested.

Example synthetic relationships:

- evening contact increases response probability for one segment
- reminder completion improves promise-to-pay completion for one cohort
- certain behaviors form clearly separable clusters
- some outcomes remain noisy and should not appear statistically significant

The ground truth must be hidden from the analysis agents but available to the evaluation harness.

---

# 21. Project Structure Recommendation

The exact naming can adapt to the existing repository, but the target organization should resemble:

```text
settle-wise/
├── server/
│   ├── agent/
│   │   ├── prompt.md
│   │   ├── orchestrator.py
│   │   ├── strategy_agent.py
│   │   ├── critic_agent.py
│   │   └── tools.py
│   │
│   ├── intelligence/
│   │   ├── pipeline.py
│   │   ├── features.py
│   │   ├── statistics.py
│   │   ├── prediction.py
│   │   ├── network.py
│   │   ├── recommendations.py
│   │   ├── evidence.py
│   │   └── evaluation.py
│   │
│   ├── routes/
│   │   ├── intelligence.py
│   │   └── ...existing routes...
│   │
│   ├── offer_engine.py
│   ├── scheduler.py
│   └── ...existing services...
│
├── data/
│   ├── settlewise.db
│   └── synthetic/
│       ├── generator.py
│       └── fixtures/
│
├── dashboard/
│   ├── intelligence.js
│   ├── network.js
│   └── ...existing UI...
│
├── tests/
│   ├── intelligence/
│   ├── statistics/
│   ├── prediction/
│   ├── network/
│   └── agent/
│
└── md/
    └── intelligence-requirements.md
```

Do not rewrite existing components unless necessary for integration.

---

# 22. Implementation Phases

## Phase 1 — Data & Analytics Foundation

Deliver:

- interaction event extraction
- feature pipeline
- analytics tables
- reproducible synthetic historical dataset
- portfolio metrics
- initial statistical analyses

**Exit criterion:** historical activity can be analyzed reproducibly from the existing database.

## Phase 2 — Prediction

Deliver:

- historical-rate baseline
- logistic regression
- one tree-based model
- temporal evaluation
- calibration
- model explanation

**Exit criterion:** a borrower receives a measurable payment-probability prediction with recorded model metadata.

## Phase 3 — Network Intelligence

Deliver:

- behavioral similarity graph
- nearest-neighbor retrieval
- community detection
- graph metrics
- dashboard graph visualization

**Exit criterion:** the system can retrieve and explain similar historical borrower behavior through the graph.

## Phase 4 — Multi-Agent Strategy Layer

Deliver:

- orchestrator
- statistics agent
- prediction agent
- network agent
- strategy agent
- critic agent
- evidence-backed recommendation object

**Exit criterion:** the system can generate a pre-call strategy using multiple analytical sources and produce an auditable explanation.

## Phase 5 — Closed-Loop Evaluation

Deliver:

- recommendation outcome tracking
- strategy comparison
- baseline vs intelligence experiment
- portfolio analytics
- model drift checks

**Exit criterion:** the system can quantify whether intelligence recommendations improve the simulated workflow.

---

# 23. Non-Functional Requirements

## Performance

- Existing call experience must not block on long-running analytics.
- Intelligence analysis should be asynchronous where it can exceed normal request latency.
- Cached feature snapshots may be used for read-heavy dashboard requests.

## Reliability

- Failure of the intelligence layer must not prevent the existing deterministic collection workflow from operating.
- A missing prediction must degrade to the existing strategy rather than block a call.
- A failed network analysis must not affect financial-policy decisions.

## Reproducibility

- Synthetic experiments must be seedable.
- Model versions must be recorded.
- Analytical results must record data and feature versions.

## Observability

Log:

- agent invocation
- tools used
- analysis IDs
- model version
- recommendation ID
- critic decision
- execution decision
- final observed outcome

## Security

- Secrets remain in environment variables.
- API keys must never be returned to the frontend.
- Analytics endpoints must respect existing access controls if authentication is introduced.
- Avoid exposing unnecessary borrower information in logs.

---

# 24. Acceptance Criteria

The project is considered complete when all of the following are true:

- [ ] Existing SettleWise voice/console workflow still works.
- [ ] Existing deterministic offer and policy protections remain authoritative.
- [ ] Historical interactions can be transformed into reproducible analytical data.
- [ ] Portfolio-level analytics are available through the dashboard/API.
- [ ] At least three statistically valid analyses are implemented.
- [ ] At least one prediction problem has a baseline and ML comparison.
- [ ] Predictions are evaluated using time-aware validation.
- [ ] A behavioral similarity graph is generated from real project data.
- [ ] Network metrics and communities can be inspected.
- [ ] A multi-agent workflow can combine statistical, predictive, and network evidence.
- [ ] A critic agent can reject unsupported recommendations.
- [ ] Every recommendation stores evidence references.
- [ ] The system distinguishes recommendation from executable action.
- [ ] Intelligence-layer failure does not break the core collections workflow.
- [ ] Baseline vs intelligence evaluation can be reproduced using synthetic data.

---

# 25. Example End-to-End Scenario

## Input

Operator selects `debt_002` and clicks **Prepare Next Collection Strategy**.

## System behavior

```text
Orchestrator
   ↓
Data Agent
   ├── loads history
   └── validates data
   ↓
Prediction Agent
   └── payment probability = 0.72
   ↓
Statistics Agent
   └── evening contact shows positive association in relevant cohort
   ↓
Network Agent
   └── borrower matches a high-response historical community
   ↓
Strategy Agent
   └── recommends evening contact + direct/flexible style
   ↓
Critic Agent
   └── validates evidence and confidence
   ↓
Policy Service
   └── confirms executable constraints
   ↓
Existing Voice Agent
   └── performs the call
   ↓
Call Outcome
   ↓
Interaction Event
   ↓
Evaluation
```

## Example final operator view

```text
NEXT BEST ACTION
----------------
Call borrower
Preferred window: 6:00 PM – 8:00 PM
Expected payment probability: 72%
Behavior cohort: Delayed but Responsive
Recommended style: Direct + Flexible
Human review: Not currently required

WHY
---
1. High historical response rate during evening contact.
2. Similar borrowers show stronger payment conversion in this window.
3. Recent promise-to-pay behavior increases the predicted probability.

IMPORTANT
---------
This recommendation does not authorize a new payment amount.
All offers remain subject to the existing deterministic offer engine.
```

---

# 26. Final Architecture Principle

SettleWise 2.0 should not become a collection of unrelated AI demos.

The intended chain is:

```text
Operational data
      ↓
Reliable analytical representation
      ↓
Statistics + ML + Network analysis
      ↓
Specialized agents interpret results
      ↓
Critic validates evidence
      ↓
Strategy recommendation
      ↓
Existing deterministic policy engine
      ↓
Existing voice/payment workflow
      ↓
Observed outcome
      ↓
Continuous evaluation
```

The project should demonstrate that **LLM agents can orchestrate rigorous data analysis while deterministic software remains responsible for decisions that affect money or policy**.

That separation is a core product requirement, not merely an implementation preference.
