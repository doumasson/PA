from pa.exceptions import (
    PAError,
    VaultAuthError,
    VaultLockedError,
    ScraperLoginError,
    ScraperMFATimeout,
    ScraperParseError,
    StoreConnectionError,
    BrainAPIError,
    BrainCostCapError,
)


def test_all_exceptions_inherit_from_pa_error():
    exceptions = [
        VaultAuthError, VaultLockedError,
        ScraperLoginError, ScraperMFATimeout, ScraperParseError,
        StoreConnectionError,
        BrainAPIError, BrainCostCapError,
    ]
    for exc_cls in exceptions:
        assert issubclass(exc_cls, PAError)


def test_exceptions_carry_message():
    err = VaultAuthError("wrong password")
    assert str(err) == "wrong password"


def test_scraper_errors_carry_institution():
    err = ScraperLoginError("login failed", institution="wellsfargo")
    assert err.institution == "wellsfargo"
    assert "login failed" in str(err)
