"""Encrypted cookie persistence for browser sessions."""

import time
from typing import Any


_SESSIONS_KEY = "_sessions"


class SessionStore:
    """Stores browser cookies in the vault, encrypted at rest.

    Cookies are stored under the _SESSIONS_KEY in the vault data dict.
    The /creds command must filter this key out to avoid showing it as an institution.
    """

    def __init__(self, vault: Any):
        self._vault = vault

    def _get_sessions(self) -> dict[str, Any]:
        return self._vault._data.get(_SESSIONS_KEY, {})

    async def save_cookies(self, institution: str, cookies: list[dict]) -> None:
        sessions = self._get_sessions()
        sessions[institution] = cookies
        self._vault._data[_SESSIONS_KEY] = sessions
        await self._vault._save()

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
        self._vault._data[_SESSIONS_KEY] = sessions
        await self._vault._save()
