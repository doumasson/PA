"""Base exception hierarchy for PA core."""

class PAError(Exception):
    """Base exception for all PA errors."""

class VaultAuthError(PAError):
    """Wrong master password."""

class VaultLockedError(PAError):
    """Operation attempted while vault is locked."""

class StoreConnectionError(PAError):
    """Database file missing or corrupt."""

class BrainAPIError(PAError):
    """Claude API returned error after retries."""

class BrainCostCapError(PAError):
    """Monthly cost cap exceeded."""
