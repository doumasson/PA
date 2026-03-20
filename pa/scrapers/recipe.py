"""Learn-once recipe engine — records and replays browser action sequences."""
import json
import re
from typing import Any

from pa.core.store import Store

CRED_ALLOWLIST = {"username", "password"}
CURRENT_SCHEMA_VERSION = 1
_CRED_PATTERN = re.compile(r"\$cred\.(\w+)")


def _validate_steps(steps: list[dict[str, Any]]) -> None:
    for step in steps:
        for value in step.values():
            if isinstance(value, str):
                for match in _CRED_PATTERN.finditer(value):
                    field = match.group(1)
                    if field not in CRED_ALLOWLIST:
                        raise ValueError(
                            f"Credential field '{field}' not in allowlist. "
                            f"Allowed: {CRED_ALLOWLIST}"
                        )


class RecipeEngine:
    def __init__(self, store: Store):
        self._store = store

    async def has_recipe(self, name: str) -> bool:
        row = await self._store.fetchone(
            "SELECT id FROM recipes WHERE name = ? AND schema_version >= ?",
            (name, CURRENT_SCHEMA_VERSION),
        )
        return row is not None

    async def get_recipe(self, name: str) -> dict[str, Any] | None:
        return await self._store.fetchone(
            "SELECT * FROM recipes WHERE name = ?", (name,)
        )

    async def record(self, name: str, plugin: str, steps: list[dict[str, Any]]) -> None:
        _validate_steps(steps)
        steps_json = json.dumps(steps)
        existing = await self.get_recipe(name)
        if existing:
            await self._store.execute(
                "UPDATE recipes SET steps = ?, schema_version = ?, fail_count = 0, updated_at = CURRENT_TIMESTAMP WHERE name = ?",
                (steps_json, CURRENT_SCHEMA_VERSION, name),
            )
        else:
            await self._store.execute(
                "INSERT INTO recipes (plugin, name, steps, schema_version) VALUES (?, ?, ?, ?)",
                (plugin, name, steps_json, CURRENT_SCHEMA_VERSION),
            )

    async def mark_stale(self, name: str) -> None:
        await self._store.execute(
            "UPDATE recipes SET fail_count = fail_count + 1, updated_at = CURRENT_TIMESTAMP WHERE name = ?",
            (name,),
        )

    async def mark_success(self, name: str) -> None:
        await self._store.execute(
            "UPDATE recipes SET last_success = CURRENT_TIMESTAMP, fail_count = 0, updated_at = CURRENT_TIMESTAMP WHERE name = ?",
            (name,),
        )

    def resolve_credentials(self, steps: list[dict[str, Any]], credentials: dict[str, str]) -> list[dict[str, Any]]:
        resolved = []
        for step in steps:
            new_step = {}
            for k, v in step.items():
                if isinstance(v, str) and "$cred." in v:
                    for match in _CRED_PATTERN.finditer(v):
                        field = match.group(1)
                        v = v.replace(f"$cred.{field}", credentials.get(field, ""))
                new_step[k] = v
            resolved.append(new_step)
        return resolved
