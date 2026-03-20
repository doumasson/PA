from pathlib import Path
from typing import Any
import aiosqlite
from pa.plugins import _validate_ddl

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class Store:
    def __init__(self, db_path: Path, encryption_key: bytes | None = None):
        self._db_path = db_path
        self._encryption_key = encryption_key
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        if self._encryption_key:
            hex_key = self._encryption_key.hex()
            await self._db.execute(f"PRAGMA key = \"x'{hex_key}'\"")
        await self._db.execute("PRAGMA foreign_keys = ON")

    async def init_schema(self) -> None:
        schema = _SCHEMA_PATH.read_text(encoding="utf-8")
        await self._db.executescript(schema)

    async def init_plugin_schema(self, plugin_name: str, ddl: str) -> None:
        _validate_ddl(ddl, plugin_name)
        await self._db.executescript(ddl)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def reconnect_encrypted(self, encryption_key: bytes) -> None:
        await self.close()
        self._encryption_key = encryption_key
        await self.connect()
        await self.init_schema()

    async def execute(self, sql: str, params: tuple = ()) -> int:
        cursor = await self._db.execute(sql, params)
        await self._db.commit()
        return cursor.lastrowid

    async def executemany(self, sql: str, params_list: list[tuple]) -> None:
        await self._db.executemany(sql, params_list)
        await self._db.commit()

    async def fetchone(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        cursor = await self._db.execute(sql, params)
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def fetchall(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
