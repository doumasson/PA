"""Async REST client for Home Assistant.

The HA box does not exist yet — this client reads config lazily on every
call, so the moment `homeassistant.url` and `homeassistant.token` land in
config.local.json (and config reloads), it starts working. Until then
`configured` is False and nothing ever touches the network.

httpx is imported lazily inside the request path so the plugin loads and
stays politely inert even on a box where httpx isn't installed yet.
"""
from __future__ import annotations

from typing import Any

_TIMEOUT_SECONDS = 10.0


class HAError(Exception):
    """A Home Assistant request failed (network, auth, or bad response)."""


class HAClient:
    """Thin wrapper over the Home Assistant REST API.

    One short-lived connection per call: Albus talks to HA a few times a
    minute at most, and this keeps the client stateless and reload-proof.
    """

    def __init__(self, config: Any):
        self._config = config

    # -- configuration ---------------------------------------------------

    def _settings(self) -> tuple[str, str] | None:
        cfg = self._config.get("homeassistant") if self._config else None
        if not isinstance(cfg, dict):
            return None
        url, token = cfg.get("url"), cfg.get("token")
        if not url or not token:
            return None
        return str(url).rstrip("/"), str(token)

    @property
    def configured(self) -> bool:
        return self._settings() is not None

    # -- REST ------------------------------------------------------------

    async def _request(self, method: str, path: str, json_body: dict | None = None) -> Any:
        settings = self._settings()
        if settings is None:
            raise HAError("Home Assistant is not configured")
        base_url, token = settings
        try:
            import httpx
        except ImportError as e:
            raise HAError("httpx is not installed; pip install httpx") from e
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                resp = await client.request(
                    method, f"{base_url}{path}", headers=headers, json=json_body
                )
        except httpx.HTTPError as e:
            raise HAError(f"Home Assistant unreachable at {base_url}: {e}") from e
        if resp.status_code >= 400:
            raise HAError(
                f"Home Assistant returned {resp.status_code} for {method} {path}"
            )
        try:
            return resp.json()
        except ValueError as e:
            raise HAError(f"Home Assistant sent non-JSON for {path}") from e

    async def ping(self) -> dict:
        """GET /api/ — cheap liveness + auth check."""
        return await self._request("GET", "/api/")

    async def states(self) -> list[dict]:
        """GET /api/states — every entity with state and attributes."""
        return await self._request("GET", "/api/states")

    async def state(self, entity_id: str) -> dict:
        """GET /api/states/<entity_id> — one entity."""
        return await self._request("GET", f"/api/states/{entity_id}")

    async def call_service(
        self, domain: str, service: str, entity_id: str | None = None, **data: Any
    ) -> Any:
        """POST /api/services/<domain>/<service> — make something happen."""
        payload: dict[str, Any] = dict(data)
        if entity_id:
            payload["entity_id"] = entity_id
        return await self._request(
            "POST", f"/api/services/{domain}/{service}", json_body=payload
        )
