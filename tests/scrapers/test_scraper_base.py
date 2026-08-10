# tests/scrapers/test_scraper_base.py
import pytest
from pa.scrapers.base import BaseScraper, BalanceData, TransactionData


def test_balance_data():
    b = BalanceData(balance=1500.0, due_date="2026-03-25")
    assert b.balance == 1500.0
    assert b.due_date == "2026-03-25"


def test_transaction_data():
    t = TransactionData(date="2026-03-15", description="GROCERY", amount=-85.0)
    assert t.amount == -85.0
    assert not t.is_pending


def test_base_scraper_is_abstract():
    with pytest.raises(TypeError):
        BaseScraper(context=None, mfa_bridge=None)
