"""Config v2 — config.json (tracked, no PII) + config.local.json (untracked overlay).

The overlay deep-merges over the base, so personal values (telegram_user_id,
profile, income) and machine-specific values (data_dir on the SSD) live only
in config.local.json. `update()` writes to the overlay, never the tracked file.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any


def _deep_merge(base: dict, overlay: dict) -> dict:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class Config:
    def __init__(self, path: Path):
        self._path = path
        self._local_path = path.with_name("config.local.json")
        self._data: dict[str, Any] = {}
        self._local: dict[str, Any] = {}

    async def load(self) -> None:
        if not self._path.exists():
            raise FileNotFoundError(f"Config file not found: {self._path}")
        text = await asyncio.to_thread(self._path.read_text, encoding="utf-8")
        base = json.loads(text)
        self._local = {}
        if self._local_path.exists():
            local_text = await asyncio.to_thread(
                self._local_path.read_text, encoding="utf-8"
            )
            self._local = json.loads(local_text)
        self._data = _deep_merge(base, self._local)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def as_dict(self) -> dict[str, Any]:
        """Merged view (base + local overlay)."""
        return dict(self._data)

    async def update(self, key: str, value: Any) -> None:
        """Persist a runtime change to the local overlay (never the tracked file)."""
        self._data[key] = value
        self._local[key] = value
        content = json.dumps(self._local, indent=2, ensure_ascii=False)
        await asyncio.to_thread(self._local_path.write_text, content, encoding="utf-8")
