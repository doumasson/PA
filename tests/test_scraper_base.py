from pa.scrapers.base import BalanceData, TransactionData, BaseScraper


def test_balance_data_defaults():
    b = BalanceData(balance=1500.00)
    assert b.balance == 1500.00
    assert b.statement_balance is None
    assert b.available_credit is None
    assert b.minimum_payment is None
    assert b.due_date is None


def test_balance_data_full():
    b = BalanceData(
        balance=2500.00,
        statement_balance=2200.00,
        available_credit=2500.00,
        minimum_payment=35.00,
        due_date="2026-03-25",
    )
    assert b.minimum_payment == 35.00


def test_transaction_data_defaults():
    t = TransactionData(date="2026-03-15", description="AMAZON", amount=49.99)
    assert t.is_pending is False
    assert t.posted_date is None


def test_base_scraper_is_abstract():
    import pytest
    from unittest.mock import MagicMock
    with pytest.raises(TypeError):
        BaseScraper(context=MagicMock(), mfa_bridge=MagicMock())
