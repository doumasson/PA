import asyncio
import json
from pathlib import Path
from typing import Any


class Config:
    def __init__(self, path: Path):
        self._path = path
        self._data: dict[str, Any] = {}

    async def load(self) -> None:
        if not self._path.exists():
            raise FileNotFoundError(f"Config file not found: {self._path}")
        text = await asyncio.to_thread(self._path.read_text, encoding="utf-8")
        self._data = json.loads(text)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    async def update(self, key: str, value: Any) -> None:
        self._data[key] = value
        content = json.dumps(self._data, indent=2, ensure_ascii=False)
        await asyncio.to_thread(self._path.write_text, content, encoding="utf-8")
