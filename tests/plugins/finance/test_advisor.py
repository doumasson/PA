# tests/plugins/finance/test_advisor.py
from pa.plugins.finance.advisor import _same_account


def test_same_card_different_wording():
    assert _same_account(
        "Mission Lane", "Mission Lane Cash Back Visa",
        "Mission Lane", "Cash Back Visa ending 4009",
    )


def test_same_card_matching_last4():
    assert _same_account(
        "Citibank", "The Home Depot Consumer Credit Card ending 8789",
        "Citi", "Home Depot card ...8789",
    )


def test_different_last4_is_different_card():
    assert not _same_account(
        "CreditOne", "Visa ending 1234",
        "CreditOne", "Visa ending 5678",
    )


def test_distinct_products_same_institution():
    assert not _same_account(
        "CreditOne", "American Express",
        "CreditOne", "Visa",
    )


def test_different_institution():
    assert not _same_account(
        "Synchrony Bank", "MyLowe's Rewards Credit Card",
        "Citibank", "Home Depot",
    )


def test_generic_names_same_institution_merge():
    assert _same_account("Brigit", "Brigit", "Brigit", "Brigit Cash Advance")
