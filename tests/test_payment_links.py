"""Regression tests for the payment-link money path.

These cover three defects found by red-teaming the agent: two by calling the
tools directly with hostile arguments (a jailbroken agent), and one that the
model produced on its own during a scripted negotiation.

Before the fix, send_sms_payment_link accepted any figure and /pay/{id}
handed it straight to mark_paid(), so a $999,999 link on a $5,050 debt
settled it outright and a -$500 link *raised* the balance.
"""

import sqlite3
import uuid

import pytest

from server import config
from server.agent import tools
from server.db import get_conn, init_db


@pytest.fixture()
def debt(monkeypatch, tmp_path):
    """A throwaway debt in a throwaway database, so these never touch the
    demo data and never text anyone."""
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", str(db_file))
    monkeypatch.setattr(tools.a1mobile_client, "send_sms", lambda to, body: {"stubbed": True})
    init_db()
    debt_id = f"t_{uuid.uuid4().hex[:8]}"
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO debts (id, name, phone, amount_due, amount_collected, status) VALUES (?, ?, ?, ?, ?, 'new')",
            (debt_id, "Test Borrower", "+15555550000", 5050.0, 0.0),
        )
    return debt_id


def _link_rows(debt_id: str) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM sms_messages WHERE debt_id = ? AND type = 'payment_link' ORDER BY sent_at", (debt_id,)
        ).fetchall()]


# -- amount validation -------------------------------------------------------


def test_link_above_outstanding_is_clamped_not_minted(debt):
    """A $999,999 link on a $5,050 balance used to settle the debt outright
    once tapped."""
    result = tools.send_sms_payment_link(debt, amount=999999)
    assert result.get("amount") == 5050.0
    assert "note" in result  # tells the agent it was clamped
    assert _link_rows(debt)[0]["amount"] == 5050.0


@pytest.mark.parametrize("bad", [-500, 0, -0.01])
def test_non_positive_link_is_refused(debt, bad):
    """A negative link used to *increase* what the borrower owed."""
    result = tools.send_sms_payment_link(debt, amount=bad)
    assert "error" in result
    assert result.get("payment_link") is None
    assert _link_rows(debt) == []


def test_non_numeric_amount_is_refused(debt):
    assert "error" in tools.send_sms_payment_link(debt, amount="lots")


def test_link_refused_when_nothing_outstanding(debt):
    tools.mark_paid(debt, 5050.0)
    assert "error" in tools.send_sms_payment_link(debt, amount=100)


# -- only one live link at a time --------------------------------------------


def test_new_link_supersedes_the_previous_one(debt):
    """The agent renegotiated mid-call ($200 then $100) and left both links
    payable - $300 collectable against a $139 instalment."""
    first = tools.send_sms_payment_link(debt, amount=200)
    second = tools.send_sms_payment_link(debt, amount=100)

    rows = {r["payment_id"]: r for r in _link_rows(debt)}
    assert rows[first["payment_id"]]["payment_status"] == "superseded"
    assert rows[second["payment_id"]]["payment_status"] == "sent"
    assert second["superseded_previous_links"] == 1


def test_paid_links_are_not_superseded_by_a_later_one(debt):
    """Superseding must only touch links still awaiting payment - a
    completed payment stays a completed payment."""
    first = tools.send_sms_payment_link(debt, amount=200)
    tools.mark_paid(debt, 200.0, sms_id=first["sms_id"])
    tools.send_sms_payment_link(debt, amount=100)

    rows = {r["payment_id"]: r for r in _link_rows(debt)}
    assert rows[first["payment_id"]]["payment_status"] == "paid"


# -- mark_paid is the last gate ----------------------------------------------


@pytest.mark.parametrize("bad", [-500, 0])
def test_mark_paid_refuses_non_positive(debt, bad):
    before = tools._debt_row(debt)["amount_collected"]
    result = tools.mark_paid(debt, bad)
    assert "error" in result
    assert tools._debt_row(debt)["amount_collected"] == before


def test_mark_paid_still_allows_overpayment(debt):
    """Duplicate payments and rounding drift are real; offer_engine already
    floors the remaining balance at zero, so this stays permitted."""
    tools.mark_paid(debt, 6000.0)
    row = tools._debt_row(debt)
    assert row["amount_collected"] == 6000.0
    assert row["status"] == "paid"


# -- round 2: findings from the second red-team pass -------------------------


def test_link_sms_id_cannot_settle_a_different_debt(debt, monkeypatch):
    """A link minted for one borrower must not be markable paid by crediting
    another - the money landed on B while A's link was cleared."""
    other = f"t_{uuid.uuid4().hex[:8]}"
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO debts (id, name, phone, amount_due, amount_collected, status) "
            "VALUES (?, 'Other', '+15555550001', 900.0, 0.0, 'new')",
            (other,),
        )
    link = tools.send_sms_payment_link(debt, amount=100)
    tools.mark_paid(other, 100.0, sms_id=link["sms_id"])

    with get_conn() as conn:
        status = conn.execute(
            "SELECT payment_status FROM sms_messages WHERE id = ?", (link["sms_id"],)
        ).fetchone()[0]
    assert status == "sent"


@pytest.mark.parametrize("bad", ["paid\" onmouseover=\"alert(1)", "<script>", "not_a_status"])
def test_status_must_be_a_known_value(debt, bad):
    """status is rendered as a CSS class on the dashboard, so a free-text
    value breaks out of the attribute."""
    assert "error" in tools.update_debt_status(debt, status=bad)


def test_call_summary_is_bounded(debt):
    result = tools.update_debt_status(debt, status="new", last_call_summary="A" * 50_000)
    assert len(result["last_call_summary"]) == tools.SUMMARY_MAX_CHARS


def test_payment_link_sms_is_rate_limited(debt, monkeypatch):
    """Superseding keeps one link payable but never capped how many texts
    went out - real cost, and a harassment vector."""
    sent = []
    monkeypatch.setattr(tools.a1mobile_client, "send_sms", lambda to, body: sent.append(to) or {"ok": True})
    for _ in range(20):
        tools.send_sms_payment_link(debt, amount=50, live=True)
    assert len(sent) == tools.MAX_PAYMENT_LINKS_PER_DAY


def test_account_ref_brute_force_is_locked_out(debt):
    results = [tools.verify_account_ref(debt, f"{i:04d}") for i in range(10)]
    assert any(r.get("locked") for r in results)
    assert results[-1]["verified"] is False


def test_bool_is_not_a_payment_amount(debt):
    """bool is an int subclass, so True quietly became a $1.00 link."""
    assert "error" in tools.send_sms_payment_link(debt, amount=True)
    assert "error" in tools.mark_paid(debt, True)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "50", None])
def test_discount_rejects_non_numbers_and_nan(debt, bad):
    """NaN fails every comparison, so a bare range check approved it and
    returned a NaN settlement."""
    assert tools.apply_discount(debt, bad)["approved"] is False
