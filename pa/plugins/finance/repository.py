import datetime as _dt
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

    @staticmethod
    def _amount_dedup_hash(account_id: int, txn_date: str, amount: float) -> str:
        """Coarse dedup: same account + date + amount = same transaction.
        Teller often sends both a short and long description for each charge."""
        raw = f"{account_id}|{txn_date}|{amount}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def add_transaction(self, account_id: int, date: str, description: str, amount: float,
                              posted_date: str | None = None, category: str | None = None,
                              is_pending: bool = False, teller_id: str | None = None) -> bool:
        # teller_id is unique per real-world transaction and survives the
        # pending -> posted re-date, so it makes the strongest dedup key.
        if teller_id:
            dedup_hash = hashlib.sha256(f"teller|{teller_id}".encode()).hexdigest()
        else:
            dedup_hash = self._compute_dedup_hash(account_id, date, description, amount)

        if teller_id:
            # Teller's txn id is stable across the pending -> posted transition,
            # while date/description are NOT (banks re-date on settlement).
            # Upsert by teller_id so the settled charge updates the pending row
            # instead of landing as a second transaction.
            existing = await self._store.fetchone(
                "SELECT id FROM finance_transactions WHERE teller_id = ?", (teller_id,)
            )
            if existing is None:
                existing = await self._adopt_legacy_twin(account_id, date, description, amount)
            if existing:
                # amount included so a re-sync also repairs rows stored with
                # the wrong sign before the Teller sign convention was honored.
                await self._store.execute(
                    "UPDATE finance_transactions SET date = ?, posted_date = ?, description = ?, "
                    "amount = ?, is_pending = ?, dedup_hash = ?, teller_id = ? WHERE id = ?",
                    (date, posted_date, description, amount, is_pending, dedup_hash, teller_id, existing["id"]),
                )
                return False

        # Same account+date+amount with different description (Teller duplicates)
        existing = await self._store.fetchone(
            "SELECT id, description FROM finance_transactions WHERE account_id = ? AND date = ? AND amount = ?"
            + (" AND teller_id IS NULL" if teller_id else ""),
            (account_id, date, amount),
        )
        if existing:
            # Keep the longer (more descriptive) version
            if len(description) > len(existing['description']):
                await self._store.execute(
                    "UPDATE finance_transactions SET description = ?, dedup_hash = ? WHERE id = ?",
                    (description, dedup_hash, existing['id']),
                )
            return False  # Not a new transaction

        # Auto-categorize at ingest if no category provided
        if not category or category in ("general", ""):
            from pa.plugins.finance.merchants import get_category
            category = await get_category(self._store, description)

        rows_affected = await self._store.execute_rowcount(
            "INSERT OR IGNORE INTO finance_transactions (account_id, date, posted_date, description, amount, category, dedup_hash, is_pending, teller_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (account_id, date, posted_date, description, amount, category, dedup_hash, is_pending, teller_id),
        )
        return rows_affected > 0

    async def _adopt_legacy_twin(self, account_id: int, date: str, description: str,
                                 amount: float) -> dict[str, Any] | None:
        """Find a pre-teller_id row that is really this same transaction.

        Rows synced before teller_id existed can't be matched by id, so match
        by account + amount + merchant with the date within 3 days (settlement
        re-dating shifts it 1-2 days). Prefers the closest date.
        """
        from pa.plugins.finance.guardian import normalize_merchant
        # Match on ABS(amount): legacy rows predate honoring Teller's sign
        # convention, so a deposit may be stored with the opposite sign.
        candidates = await self._store.fetchall(
            """SELECT id, date, description FROM finance_transactions
               WHERE teller_id IS NULL AND account_id = ? AND ABS(amount) = ABS(?)
                 AND date BETWEEN date(?, '-3 days') AND date(?, '+3 days')""",
            (account_id, amount, date, date),
        )
        merchant = normalize_merchant(description)
        matches = [c for c in candidates if normalize_merchant(c["description"]) == merchant]
        if not matches:
            return None
        target = _dt.date.fromisoformat(date)
        return min(matches, key=lambda c: abs((_dt.date.fromisoformat(c["date"]) - target).days))

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

    async def get_monthly_spending(self, months: int = 6) -> list[dict[str, Any]]:
        """Get spending totals by month for the last N months."""
        return await self._store.fetchall(
            """SELECT strftime('%Y-%m', date) AS month,
                      SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS spending,
                      SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END) AS income,
                      COUNT(*) AS txn_count
               FROM finance_transactions
               WHERE date >= date('now', ? || ' months')
               GROUP BY month ORDER BY month""",
            (str(-months),),
        )

    async def get_monthly_by_category(self, month: str) -> list[dict[str, Any]]:
        """Get spending by category for a specific month (YYYY-MM)."""
        return await self._store.fetchall(
            """SELECT COALESCE(category, 'Uncategorized') AS category,
                      SUM(amount) AS total,
                      COUNT(*) AS txn_count
               FROM finance_transactions
               WHERE strftime('%Y-%m', date) = ? AND amount > 0
               GROUP BY category ORDER BY total DESC""",
            (month,),
        )

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
