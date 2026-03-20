from pa.core.exceptions import (
    PAError, VaultAuthError, VaultLockedError,
    StoreConnectionError, BrainAPIError, BrainCostCapError,
)

def test_hierarchy():
    assert issubclass(VaultAuthError, PAError)
    assert issubclass(VaultLockedError, PAError)
    assert issubclass(StoreConnectionError, PAError)
    assert issubclass(BrainAPIError, PAError)
    assert issubclass(BrainCostCapError, PAError)

def test_raise_and_catch():
    try:
        raise VaultLockedError("locked")
    except PAError as e:
        assert "locked" in str(e)
