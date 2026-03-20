import hashlib
from typing import Any
from pa.core.store import Store


class FinanceRepository:
    def __init__(self, store: Store):
        self._store = store

    async def add_account(self, institution: str, name: str, account_type: str,
                          interest_rate: float | None = None, credit_limit: float | None = None) -> int:
        return await self._store.execute(
            "INSERT INTO finance_accounts (institution, name, type, interest_rate, credit_limit) VALUES (?, ?, ?, ?, ?)",
            (institution, name, account_type, interest_rate, credit_limit),
        )

    async def get_accounts(self) -> list[dict[str, Any]]:
        return await self._store.fetchall("SELECT * FROM finance_accounts ORDER BY id")

    async def add_balance(self, account_id: int, balance: float,
                          statement_balance: float | None = None, available_credit: float | None = None,
                          minimum_payment: float | None = None, due_date: str | None = None) -> int:
        return await self._store.execute(
            "INSERT INTO finance_balances (account_id, balance, statement_balance, available_credit, minimum_payment, due_date) VALUES (?, ?, ?, ?, ?, ?)",
            (account_id, balance, statement_balance, available_credit, minimum_payment, due_date),
        )

    async def get_latest_balances(self) -> list[dict[str, Any]]:
        return await self._store.fetchall("""
            SELECT b.*, a.institution, a.name, a.type, a.interest_rate, a.credit_limit
            FROM finance_balances b
            JOIN finance_accounts a ON a.id = b.account_id
            WHERE b.id IN (SELECT MAX(id) FROM finance_balances GROUP BY account_id)
            ORDER BY a.id
        """)

    @staticmethod
    def _compute_dedup_hash(account_id: int, txn_date: str, description: str, amount: float) -> str:
        raw = f"{account_id}|{txn_date}|{description}|{amount}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def add_transaction(self, account_id: int, date: str, description: str, amount: float,
                              posted_date: str | None = None, category: str | None = None, is_pending: bool = False) -> bool:
        dedup_hash = self._compute_dedup_hash(account_id, date, description, amount)
        rows_affected = await self._store.execute_rowcount(
            "INSERT OR IGNORE INTO finance_transactions (account_id, date, posted_date, description, amount, category, dedup_hash, is_pending) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (account_id, date, posted_date, description, amount, category, dedup_hash, is_pending),
        )
        return rows_affected > 0

    async def get_transactions(self, account_id: int | None = None, since_date: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT * FROM finance_transactions WHERE 1=1"
        params: list[Any] = []
        if account_id is not None:
            query += " AND account_id = ?"
            params.append(account_id)
        if since_date is not None:
            query += " AND date >= ?"
            params.append(since_date)
        query += " ORDER BY date DESC LIMIT ?"
        params.append(limit)
        return await self._store.fetchall(query, tuple(params))

    async def log_scrape(self, institution: str, status: str, account_id: int | None = None,
                         error_message: str | None = None, duration_seconds: float | None = None) -> None:
        await self._store.execute(
            "INSERT INTO finance_scrape_log (institution, account_id, status, error_message, duration_seconds) VALUES (?, ?, ?, ?, ?)",
            (institution, account_id, status, error_message, duration_seconds),
        )

    async def get_scrape_logs(self, limit: int = 20) -> list[dict[str, Any]]:
        return await self._store.fetchall(
            "SELECT * FROM finance_scrape_log ORDER BY ran_at DESC LIMIT ?", (limit,)
        )
