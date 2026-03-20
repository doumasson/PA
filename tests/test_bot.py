import pytest
from unittest.mock import AsyncMock, MagicMock

from pa.bot.handlers import (
    is_authorized,
    format_balance_summary,
    format_debt_summary,
    format_due_summary,
    format_spending_summary,
)


def test_is_authorized_correct_user():
    assert is_authorized(123456789, 123456789)


def test_is_authorized_wrong_user():
    assert not is_authorized(999999999, 123456789)


def test_format_balance_summary():
    balances = [
        {"name": "WF Checking", "type": "checking", "balance": 1500.00, "institution": "wellsfargo"},
        {"name": "Synchrony Card", "type": "credit_card", "balance": 2500.00, "institution": "synchrony", "credit_limit": 5000.0},
    ]
    result = format_balance_summary(balances)
    assert "WF Checking" in result
    assert "$1,500.00" in result
    assert "Synchrony Card" in result


def test_format_debt_summary():
    balances = [
        {"name": "WF Checking", "type": "checking", "balance": 1500.00, "institution": "wellsfargo"},
        {"name": "Synchrony Card", "type": "credit_card", "balance": 2500.00, "institution": "synchrony", "interest_rate": 0.2499},
        {"name": "Credit One", "type": "credit_card", "balance": 1200.00, "institution": "creditone", "interest_rate": 0.2399},
    ]
    result = format_debt_summary(balances)
    assert "Synchrony Card" in result
    assert "Credit One" in result
    assert "WF Checking" not in result
    assert "$3,700.00" in result


def test_format_due_summary():
    balances = [
        {"name": "Synchrony Card", "type": "credit_card", "balance": 2500.00, "minimum_payment": 35.00, "due_date": "2026-03-25"},
        {"name": "Credit One", "type": "credit_card", "balance": 1200.00, "minimum_payment": 25.00, "due_date": "2026-04-01"},
    ]
    result = format_due_summary(balances)
    assert "Synchrony Card" in result
    assert "$35.00" in result
    assert "2026-03-25" in result


def test_format_spending_summary():
    transactions = [
        {"category": "food", "amount": 85.00},
        {"category": "food", "amount": 45.00},
        {"category": "gas", "amount": 60.00},
        {"category": None, "amount": 20.00},
    ]
    result = format_spending_summary(transactions, "this week")
    assert "food" in result.lower()
    assert "$130.00" in result
