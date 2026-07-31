"""Synthetic collections policy (md/technical-spec.md "Synthetic Policy").

Gives the agent/simulator boundaries: call windows, discount/installment
caps, and human-review triggers. Stored as a single DB row so it can be
read like any other tool-backed fact rather than hardcoded in the agent.
"""

from .db import DEFAULT_POLICY_ID, get_conn


def get_policy(policy_id: str = DEFAULT_POLICY_ID) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM policies WHERE id = ?", (policy_id,)).fetchone()
    if row is None:
        return {"error": f"No policy found for id {policy_id}"}
    policy = dict(row)
    policy["human_review_triggers"] = policy["human_review_triggers"].split(",")
    policy["allowed_call_hours"] = {
        "start": policy.pop("allowed_call_hours_start"),
        "end": policy.pop("allowed_call_hours_end"),
    }
    return policy
