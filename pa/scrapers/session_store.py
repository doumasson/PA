"""Encrypted cookie persistence for browser sessions."""

import time
from typing import Any


_SESSIONS_KEY = "_sessions"


class SessionStore:
    """Stores browser cookies in the vault, encrypted at rest.

    Cookies live under _SESSIONS_KEY; "_"-prefixed keys are hidden from
    vault.institutions() so /creds never shows them.
    """

    def __init__(self, vault: Any):
        self._vault = vault

    def _get_sessions(self) -> dict[str, Any]:
        return self._vault.get(_SESSIONS_KEY) or {}

    async def save_cookies(self, institution: str, cookies: list[dict]) -> None:
        sessions = self._get_sessions()
        sessions[institution] = cookies
        await self._vault.add(_SESSIONS_KEY, sessions)

    async def load_cookies(self, institution: str) -> list[dict] | None:
        sessions = self._get_sessions()
        cookies = sessions.get(institution)
        if cookies is None:
            return None
        now = time.time()
        valid = [c for c in cookies if c.get("expires", now + 1) > now]
        if not valid:
            return None
        return valid

    async def clear_cookies(self, institution: str) -> None:
        sessions = self._get_sessions()
        sessions.pop(institution, None)
        await self._vault.add(_SESSIONS_KEY, sessions)
