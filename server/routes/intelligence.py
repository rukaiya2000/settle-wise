"""Read-only view of the intelligence layer.

Everything here is a lookup into tables R wrote, plus the recommendation
composer. Nothing mutates a debt: there is no route that can change a
status, an amount, or a floor, which is the whole point of keeping this
namespace separate from /api/debts.
"""

from __future__ import annotations

import json
import shutil
import subprocess

from fastapi import APIRouter, HTTPException

from .. import config
from ..db import get_conn, row_to_dict, rows_to_dicts
from ..intelligence.recommend import borrower_intelligence, intelligence_available, record_outcome
from ..intelligence.schema import R_OUTPUT_TABLES

router = APIRouter(prefix="/api/intelligence")

_COUNT_TABLES = [*R_OUTPUT_TABLES, "interaction_events", "intel_borrowers"]


@router.get("/status")
def status():
    with get_conn() as conn:
        count_sql = ", ".join(f"(SELECT COUNT(*) FROM {t}) AS {t}" for t in _COUNT_TABLES)
        counts = dict(conn.execute(f"SELECT {count_sql}").fetchone())
        network = row_to_dict(conn.execute("SELECT * FROM network_metrics ORDER BY built_at DESC LIMIT 1").fetchone())
        champion = row_to_dict(
            conn.execute(
                "SELECT model_version, model_name, trained_at FROM model_registry WHERE is_champion = 1 ORDER BY trained_at DESC LIMIT 1"
            ).fetchone()
        )
        available = intelligence_available(conn)
    manifest_path = config.BASE_DIR / "data" / "synthetic" / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    return {"available": available, "counts": counts, "network": network, "champion_model": champion, "synthetic": manifest}


@router.get("/summary")
def summary():
    """Per live borrower: segment and probability, for badges in the table."""
    with get_conn() as conn:
        rows = rows_to_dicts(
            conn,
            """SELECT d.id AS debt_id, s.segment_label, s.community, s.is_bridge, f.low_history,
                      (SELECT prediction_value FROM predictions p
                        WHERE p.debt_id = d.id AND p.prediction_type = 'payment_after_next_contact'
                        ORDER BY generated_at DESC LIMIT 1) AS payment_probability
               FROM debts d
               LEFT JOIN borrower_segments s ON s.debt_id = d.id
               LEFT JOIN borrower_features f ON f.debt_id = d.id""",
        )
    return {r["debt_id"]: r for r in rows}


@router.get("/borrowers/{debt_id}")
def borrower(debt_id: str):
    result = borrower_intelligence(debt_id)
    if not result.get("available") and result.get("reason") == "unknown debt":
        raise HTTPException(404, "not found")
    return result


@router.post("/recommend/{debt_id}")
def recommend(debt_id: str):
    return borrower(debt_id)


@router.post("/recommendations/{debt_id}/outcome")
def outcome(debt_id: str, body: dict):
    latest = record_outcome(debt_id, body.get("executed_action"), body.get("observed_outcome"))
    if latest is None:
        raise HTTPException(404, "no recommendation for this debt")
    return latest


@router.get("/recommendations/{recommendation_id}")
def recommendation(recommendation_id: str):
    with get_conn() as conn:
        row = row_to_dict(conn.execute("SELECT * FROM recommendations WHERE recommendation_id = ?", (recommendation_id,)).fetchone())
    if row is None:
        raise HTTPException(404, "not found")
    row["recommendation"] = json.loads(row.pop("recommendation_json"))
    row["evidence_ids"] = json.loads(row.get("evidence_ids") or "[]")
    return row


@router.get("/statistics")
def statistics():
    with get_conn() as conn:
        findings = rows_to_dicts(conn, "SELECT * FROM statistical_findings ORDER BY analysis_name, segment_label")
        segments = rows_to_dicts(conn, "SELECT * FROM segment_profiles ORDER BY community")
    return {"findings": findings, "segments": segments}


@router.get("/strategies")
def strategies():
    with get_conn() as conn:
        return rows_to_dicts(conn, "SELECT * FROM strategy_performance ORDER BY payment_rate DESC")


@router.get("/models")
def models():
    """The most recent training run's models - model_registry accumulates
    a row per model per run, not just the latest, so this is filtered to
    the newest trained_at rather than returning every run ever made."""
    with get_conn() as conn:
        rows = rows_to_dicts(
            conn,
            """SELECT * FROM model_registry
               WHERE trained_at = (SELECT MAX(trained_at) FROM model_registry)
               ORDER BY is_champion DESC, roc_auc DESC""",
        )
    for r in rows:
        r["calibration"] = json.loads(r.pop("calibration_json") or "[]")
    return rows


@router.get("/network")
def network():
    with get_conn() as conn:
        metrics = row_to_dict(conn.execute("SELECT * FROM network_metrics ORDER BY built_at DESC LIMIT 1").fetchone())
        nodes = rows_to_dicts(conn, "SELECT * FROM graph_nodes")
        edges = rows_to_dicts(conn, "SELECT * FROM graph_edges")
        segments = rows_to_dicts(conn, "SELECT * FROM segment_profiles ORDER BY community")
    return {"metrics": metrics, "nodes": nodes, "edges": edges, "segments": segments}


@router.get("/epidemiology")
def epidemiology():
    """SIR-style daily state curve plus the per-segment R_eff table, both
    written by intelligence/R/06_epidemiology.R."""
    with get_conn() as conn:
        curve = rows_to_dicts(conn, "SELECT * FROM epi_curve_daily ORDER BY segment_label, day")
        reproduction = rows_to_dicts(conn, "SELECT * FROM epi_reproduction ORDER BY r_eff DESC")
    return {"curve": curve, "reproduction": reproduction}


@router.get("/robustness")
def robustness():
    """Percolation robustness curve (targeted vs random borrower removal)
    plus its summary, both written by intelligence/R/07_percolation.R."""
    with get_conn() as conn:
        curve = rows_to_dicts(conn, "SELECT * FROM network_robustness ORDER BY strategy, removal_fraction")
        summary = row_to_dict(
            conn.execute("SELECT * FROM network_robustness_summary ORDER BY graph_version DESC LIMIT 1").fetchone()
        )
    return {"curve": curve, "summary": summary}


@router.get("/scenarios")
def scenarios():
    """Intervention scenario sweep (strategy x targeting rule x budget) and
    its per-strategy summaries, written by intelligence/R/08_scenarios.R."""
    with get_conn() as conn:
        curve = rows_to_dicts(conn, "SELECT * FROM scenario_outcomes ORDER BY strategy, targeting, k")
        summary = rows_to_dicts(conn, "SELECT * FROM scenario_summary ORDER BY strategy")
    return {"curve": curve, "summary": summary}


@router.get("/portfolio")
def portfolio():
    """Portfolio-level numbers, all computed from stored rows (no UI
    constants): live book from debts, history from intel_borrowers."""
    with get_conn() as conn:
        live = row_to_dict(conn.execute(
            """SELECT COUNT(*) AS accounts,
                      COALESCE(SUM(amount_due - amount_collected), 0) AS outstanding,
                      COALESCE(SUM(amount_collected), 0) AS collected,
                      COALESCE(SUM(amount_due), 0) AS total_due,
                      SUM(CASE WHEN status = 'needs_review' THEN 1 ELSE 0 END) AS in_review,
                      SUM(CASE WHEN status = 'paid' THEN 1 ELSE 0 END) AS paid_accounts
               FROM debts"""
        ).fetchone())
        hist = row_to_dict(conn.execute(
            """SELECT COUNT(*) AS n,
                      AVG(paid) AS payment_rate,
                      AVG(CASE WHEN final_outcome = 'needs_review' THEN 1.0 ELSE 0.0 END) AS escalation_rate,
                      AVG(CASE WHEN observed = 1 THEN days_to_payment END) AS avg_days_to_payment
               FROM intel_borrowers WHERE cohort = 'historical'"""
        ).fetchone())
        contact = row_to_dict(conn.execute(
            """SELECT AVG(CASE WHEN outcome != 'no_answer' THEN 1.0 ELSE 0.0 END) AS contact_success_rate,
                      COUNT(*) AS call_attempts
               FROM interaction_events WHERE event_type = 'call_attempt' AND cohort = 'historical'"""
        ).fetchone())
        promise = row_to_dict(conn.execute(
            """SELECT AVG(CASE WHEN b.paid = 1 THEN 1.0 ELSE 0.0 END) AS promise_completion_rate, COUNT(*) AS promises
               FROM (SELECT DISTINCT debt_id FROM interaction_events WHERE outcome = 'answered_promised' AND cohort = 'historical') p
               JOIN intel_borrowers b ON b.debt_id = p.debt_id"""
        ).fetchone())
    return {"live": live, "historical": {**hist, **contact, **promise}}


@router.post("/rebuild")
def rebuild():
    """Re-run extraction + the R pipeline. Synchronous and slow-ish (tens of
    seconds); the dashboard button that calls it says so. Runs `make
    intelligence` so the CLI and the button can never disagree."""
    # The deployed instance has no R, no make, and no writable checkout - the
    # intelligence tables are computed locally and pushed with
    # scripts/sync_intelligence.py. Fail with something explanatory rather
    # than a subprocess traceback.
    if not shutil.which("Rscript"):
        raise HTTPException(
            501,
            "Rebuild runs the R pipeline, which isn't available on this deployment. "
            "Run `make intelligence` locally, then `python scripts/sync_intelligence.py` to push the results.",
        )
    proc = subprocess.run(
        ["make", "intelligence"],
        cwd=config.BASE_DIR,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if proc.returncode != 0:
        raise HTTPException(500, f"rebuild failed:\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
    return {"ok": True, "log": proc.stdout[-4000:]}
