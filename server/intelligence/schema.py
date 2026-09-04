"""Analytics tables, kept apart from the operational ones.

The operational tables (debts, calls, sms_messages) are what the agent and
scheduler act on, and their shape is dictated by the call flow. Analysis
wants a flat event log and per-borrower snapshots instead, so those live in
their own tables here rather than overloading the operational schema.

Two kinds of table:

- Inputs Python writes: interaction_events, intel_borrowers. Filled by the
  synthetic generator (historical cohort) and the extractor (live debts).
- Outputs R writes: borrower_features, borrower_segments, ... These are
  created here too so the API can query them (and return "not built yet")
  before the R pipeline has ever run. R replaces their contents wholesale.
"""

from ..db import get_conn

SCHEMA = """
CREATE TABLE IF NOT EXISTS intel_borrowers (
    debt_id TEXT PRIMARY KEY,
    -- 'historical': closed synthetic accounts the analysis learns from.
    -- 'live': borrowers on the dashboard, extracted from operational tables.
    cohort TEXT NOT NULL,
    amount_due REAL NOT NULL,
    strategy TEXT,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    final_outcome TEXT,
    paid INTEGER NOT NULL DEFAULT 0,
    -- Survival fields: time from first contact attempt to payment, or to
    -- the last observed day if never paid (observed = 0, censored).
    days_to_payment REAL,
    observed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS interaction_events (
    event_id TEXT PRIMARY KEY,
    debt_id TEXT NOT NULL,
    cohort TEXT NOT NULL,
    event_time TEXT NOT NULL,
    -- call_attempt | sms | payment | escalation
    event_type TEXT NOT NULL,
    channel TEXT NOT NULL,
    hour INTEGER,
    time_bucket TEXT,
    weekday INTEGER,
    outcome TEXT,
    strategy TEXT,
    amount_due_at_event REAL,
    amount_offered REAL,
    amount_paid REAL,
    response_time_seconds REAL,
    metadata_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_debt ON interaction_events(debt_id, event_time);

-- ---- Written by the R pipeline (intelligence/R). ----

CREATE TABLE IF NOT EXISTS borrower_features (
    debt_id TEXT PRIMARY KEY,
    cohort TEXT,
    n_events INTEGER,
    n_calls INTEGER,
    contact_success_rate REAL,
    promise_completion_rate REAL,
    objection_rate REAL,
    evening_share REAL,
    evening_contact_rate REAL,
    daytime_contact_rate REAL,
    avg_response_time REAL,
    preferred_bucket TEXT,
    n_reminders INTEGER,
    days_active REAL,
    amount_due REAL,
    low_history INTEGER,
    feature_version TEXT
);

CREATE TABLE IF NOT EXISTS borrower_segments (
    debt_id TEXT PRIMARY KEY,
    community INTEGER,
    segment_label TEXT,
    degree INTEGER,
    betweenness REAL,
    is_bridge INTEGER,
    assigned_via TEXT,
    graph_version TEXT
);

CREATE TABLE IF NOT EXISTS borrower_neighbors (
    debt_id TEXT NOT NULL,
    neighbor_id TEXT NOT NULL,
    rank INTEGER NOT NULL,
    similarity REAL,
    neighbor_paid INTEGER,
    neighbor_segment TEXT,
    neighbor_days_to_payment REAL,
    neighbor_best_bucket TEXT,
    PRIMARY KEY (debt_id, rank)
);

CREATE TABLE IF NOT EXISTS segment_profiles (
    community INTEGER PRIMARY KEY,
    segment_label TEXT,
    n INTEGER,
    payment_rate REAL,
    ci_low REAL,
    ci_high REAL,
    best_bucket TEXT,
    best_bucket_rate REAL,
    median_days_to_payment REAL,
    contact_success_rate REAL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS predictions (
    prediction_id TEXT PRIMARY KEY,
    debt_id TEXT NOT NULL,
    prediction_type TEXT NOT NULL,
    prediction_value REAL,
    model_version TEXT,
    generated_at TEXT,
    feature_version TEXT,
    explanation_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_pred_debt ON predictions(debt_id);

CREATE TABLE IF NOT EXISTS statistical_findings (
    finding_id TEXT PRIMARY KEY,
    analysis_name TEXT,
    question TEXT,
    hypothesis TEXT,
    method TEXT,
    sample_size INTEGER,
    effect_size REAL,
    effect_label TEXT,
    p_value REAL,
    p_adjusted REAL,
    ci_low REAL,
    ci_high REAL,
    significant INTEGER,
    result_summary TEXT,
    limitations TEXT,
    segment_label TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS strategy_performance (
    strategy TEXT PRIMARY KEY,
    n INTEGER,
    payment_rate REAL,
    ci_low REAL,
    ci_high REAL,
    avg_days_to_payment REAL,
    median_days_to_payment REAL
);

CREATE TABLE IF NOT EXISTS model_registry (
    model_version TEXT PRIMARY KEY,
    model_name TEXT,
    trained_at TEXT,
    n_train INTEGER,
    n_test INTEGER,
    roc_auc REAL,
    pr_auc REAL,
    brier REAL,
    precision_at_threshold REAL,
    recall_at_threshold REAL,
    f1_at_threshold REAL,
    threshold REAL,
    positive_rate REAL,
    calibration_json TEXT,
    feature_version TEXT,
    is_champion INTEGER,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS network_metrics (
    graph_version TEXT PRIMARY KEY,
    built_at TEXT,
    n_nodes INTEGER,
    n_edges INTEGER,
    k INTEGER,
    n_communities INTEGER,
    modularity REAL,
    null_modularity_mean REAL,
    null_modularity_sd REAL,
    ari_vs_truth REAL,
    edge_definition TEXT
);

CREATE TABLE IF NOT EXISTS graph_nodes (
    debt_id TEXT PRIMARY KEY,
    community INTEGER,
    segment_label TEXT,
    x REAL,
    y REAL,
    degree INTEGER,
    betweenness REAL,
    is_bridge INTEGER,
    paid INTEGER,
    cohort TEXT
);

CREATE TABLE IF NOT EXISTS graph_edges (
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    weight REAL,
    PRIMARY KEY (source, target)
);

-- Daily S/Active/Recovered/Escalated counts, restating the survival basis
-- (days_to_payment/observed/final_outcome) already used for the Kaplan-Meier
-- curve as cumulative state counts over calendar time instead of a
-- probability over time-since-open. Written by intelligence/R/06_epidemiology.R.
CREATE TABLE IF NOT EXISTS epi_curve_daily (
    day TEXT NOT NULL,
    segment_label TEXT NOT NULL,
    n_susceptible INTEGER NOT NULL,
    n_active INTEGER NOT NULL,
    n_recovered INTEGER NOT NULL,
    n_escalated INTEGER NOT NULL,
    n_cohort INTEGER NOT NULL,
    graph_version TEXT,
    epi_version TEXT,
    created_at TEXT,
    PRIMARY KEY (day, segment_label)
);

-- Effective "reproduction number" per segment: R_eff = beta (per-attempt
-- conversion) x contact rate x duration. Explicitly not a claim of
-- borrower-to-borrower transmission - see limitation_note - it measures
-- whether outreach resolves accounts faster than they age into escalation.
CREATE TABLE IF NOT EXISTS epi_reproduction (
    segment_label TEXT PRIMARY KEY,
    n INTEGER,
    beta REAL,
    beta_n_attempts INTEGER,
    c_contacts_per_active_day REAL,
    total_calls INTEGER,
    total_active_days REAL,
    d_days REAL,
    d_tau_days REAL,
    r_eff REAL,
    r_eff_ci_low REAL,
    r_eff_ci_high REAL,
    limitation_note TEXT,
    epi_version TEXT,
    created_at TEXT
);

-- Percolation robustness of the k-NN similarity graph: largest-connected-
-- component fraction remaining as borrowers are removed, targeted
-- (highest betweenness first) vs random. Written by
-- intelligence/R/07_percolation.R.
CREATE TABLE IF NOT EXISTS network_robustness (
    graph_version TEXT NOT NULL,
    removal_fraction REAL NOT NULL,
    strategy TEXT NOT NULL,
    n_removed INTEGER,
    lcc_fraction REAL,
    lcc_fraction_sd REAL,
    n_reps INTEGER,
    PRIMARY KEY (graph_version, removal_fraction, strategy)
);

CREATE TABLE IF NOT EXISTS network_robustness_summary (
    graph_version TEXT PRIMARY KEY,
    auc_targeted REAL,
    auc_random_mean REAL,
    auc_random_sd REAL,
    robustness_gap REAL,
    -- Smallest removal_fraction where targeted removal drops more than 2
    -- random-removal SDs below the random baseline; NULL if that never
    -- happens across the tested sweep (see intelligence/R/07_percolation.R).
    onset_fraction REAL,
    n_bridge_nodes INTEGER,
    interpretation TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS recommendations (
    recommendation_id TEXT PRIMARY KEY,
    debt_id TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    recommendation_json TEXT NOT NULL,
    evidence_ids TEXT,
    executed_action TEXT,
    observed_outcome TEXT
);
CREATE INDEX IF NOT EXISTS idx_rec_debt ON recommendations(debt_id, generated_at);
"""

R_OUTPUT_TABLES = [
    "borrower_features",
    "borrower_segments",
    "borrower_neighbors",
    "segment_profiles",
    "predictions",
    "statistical_findings",
    "strategy_performance",
    "model_registry",
    "network_metrics",
    "graph_nodes",
    "graph_edges",
    "epi_curve_daily",
    "epi_reproduction",
    "network_robustness",
    "network_robustness_summary",
]


def init_intel_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def insert_intel_rows(conn, borrower: dict, events: list[dict]) -> None:
    """Shared by the synthetic generator and the live extractor - both
    populate intel_borrowers/interaction_events with rows shaped identically
    regardless of cohort."""
    conn.execute(
        """INSERT INTO intel_borrowers (debt_id, cohort, amount_due, strategy, opened_at, closed_at, final_outcome, paid, days_to_payment, observed)
        VALUES (:debt_id, :cohort, :amount_due, :strategy, :opened_at, :closed_at, :final_outcome, :paid, :days_to_payment, :observed)""",
        borrower,
    )
    for e in events:
        conn.execute(
            """INSERT INTO interaction_events
            (event_id, debt_id, cohort, event_time, event_type, channel, hour, time_bucket, weekday, outcome, strategy,
             amount_due_at_event, amount_offered, amount_paid, response_time_seconds, metadata_json)
            VALUES (:event_id, :debt_id, :cohort, :event_time, :event_type, :channel, :hour, :time_bucket, :weekday, :outcome, :strategy,
             :amount_due_at_event, :amount_offered, :amount_paid, :response_time_seconds, :metadata_json)""",
            e,
        )
