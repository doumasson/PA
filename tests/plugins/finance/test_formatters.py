# tests/plugins/finance/test_formatters.py
from pa.plugins.finance.formatters import (
    format_balance_summary, format_debt_summary, format_due_summary, format_spending_summary,
)


def test_balance_summary_empty():
    assert "No account data" in format_balance_summary([])


def test_balance_summary():
    balances = [{"name": "WF Checking", "balance": 1500.0, "credit_limit": None}]
    result = format_balance_summary(balances)
    assert "WF Checking" in result
    assert "1,500.00" in result


def test_debt_summary():
    balances = [
        {"name": "CC", "type": "credit_card", "balance": 2500.0, "interest_rate": 0.2499},
        {"name": "Checking", "type": "checking", "balance": 1500.0, "interest_rate": None},
    ]
    result = format_debt_summary(balances)
    assert "CC" in result
    assert "Checking" not in result


def test_due_summary():
    balances = [{"name": "CC", "due_date": "2026-03-25", "minimum_payment": 35.0}]
    result = format_due_summary(balances)
    assert "35.00" in result


def test_spending_summary():
    txns = [{"category": "food", "amount": -50.0}, {"category": "food", "amount": -30.0}]
    result = format_spending_summary(txns, "this month")
    assert "80.00" in result
