class PAError(Exception):
    """Base exception for all PA errors."""


class VaultAuthError(PAError):
    """Wrong master password."""


class VaultLockedError(PAError):
    """Operation attempted while vault is locked."""


class ScraperLoginError(PAError):
    """Login to financial institution failed."""

    def __init__(self, message: str, institution: str = ""):
        super().__init__(message)
        self.institution = institution


class ScraperMFATimeout(PAError):
    """MFA code not provided within timeout."""

    def __init__(self, message: str, institution: str = ""):
        super().__init__(message)
        self.institution = institution


class ScraperParseError(PAError):
    """Page layout changed, data extraction failed."""

    def __init__(self, message: str, institution: str = ""):
        super().__init__(message)
        self.institution = institution


class StoreConnectionError(PAError):
    """Database file missing or corrupt."""


class BrainAPIError(PAError):
    """Claude API returned error after retries."""


class BrainCostCapError(PAError):
    """Monthly cost cap exceeded."""
