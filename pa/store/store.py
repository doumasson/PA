import hashlib
from pathlib import Path
from typing import Any

import aiosqlite

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

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def reconnect_encrypted(self, encryption_key: bytes) -> None:
        """Close current connection and reopen with SQLCipher encryption."""
        await self.close()
        self._encryption_key = encryption_key
        await self.connect()
        await self.init_schema()

    # --- Accounts ---

    async def add_account(
        self,
        institution: str,
        name: str,
        account_type: str,
        interest_rate: float | None = None,
        credit_limit: float | None = None,
    ) -> int:
        cursor = await self._db.execute(
            "INSERT INTO accounts (institution, name, type, interest_rate, credit_limit) VALUES (?, ?, ?, ?, ?)",
            (institution, name, account_type, interest_rate, credit_limit),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def get_accounts(self) -> list[dict[str, Any]]:
        cursor = await self._db.execute("SELECT * FROM accounts ORDER BY id")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # --- Balances ---

    async def add_balance(
        self,
        account_id: int,
        balance: float,
        statement_balance: float | None = None,
        available_credit: float | None = None,
        minimum_payment: float | None = None,
        due_date: str | None = None,
    ) -> int:
        cursor = await self._db.execute(
            "INSERT INTO balances (account_id, balance, statement_balance, available_credit, minimum_payment, due_date) VALUES (?, ?, ?, ?, ?, ?)",
            (account_id, balance, statement_balance, available_credit, minimum_payment, due_date),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def get_latest_balances(self) -> list[dict[str, Any]]:
        cursor = await self._db.execute("""
            SELECT b.*, a.institution, a.name, a.type
            FROM balances b
            JOIN accounts a ON a.id = b.account_id
            WHERE b.id IN (
                SELECT MAX(id) FROM balances GROUP BY account_id
            )
            ORDER BY a.id
        """)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # --- Transactions ---

    @staticmethod
    def _compute_dedup_hash(account_id: int, txn_date: str, description: str, amount: float) -> str:
        raw = f"{account_id}|{txn_date}|{description}|{amount}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def add_transaction(
        self,
        account_id: int,
        date: str,
        description: str,
        amount: float,
        posted_date: str | None = None,
        category: str | None = None,
        is_pending: bool = False,
    ) -> bool:
        dedup_hash = self._compute_dedup_hash(account_id, date, description, amount)
        cursor = await self._db.execute(
            "INSERT OR IGNORE INTO transactions (account_id, date, posted_date, description, amount, category, dedup_hash, is_pending) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (account_id, date, posted_date, description, amount, category, dedup_hash, is_pending),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def get_transactions(
        self,
        account_id: int | None = None,
        since_date: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM transactions WHERE 1=1"
        params: list[Any] = []
        if account_id is not None:
            query += " AND account_id = ?"
            params.append(account_id)
        if since_date is not None:
            query += " AND date >= ?"
            params.append(since_date)
        query += " ORDER BY date DESC LIMIT ?"
        params.append(limit)
        cursor = await self._db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # --- Scrape Log ---

    async def log_scrape(
        self,
        institution: str,
        status: str,
        account_id: int | None = None,
        error_message: str | None = None,
        duration_seconds: float | None = None,
    ) -> None:
        await self._db.execute(
            "INSERT INTO scrape_log (institution, account_id, status, error_message, duration_seconds) VALUES (?, ?, ?, ?, ?)",
            (institution, account_id, status, error_message, duration_seconds),
        )
        await self._db.commit()

    async def get_scrape_logs(self, limit: int = 20) -> list[dict[str, Any]]:
        cursor = await self._db.execute(
            "SELECT * FROM scrape_log ORDER BY ran_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
