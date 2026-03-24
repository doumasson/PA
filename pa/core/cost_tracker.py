"""API cost tracking with database persistence."""
import datetime
from pa.core.exceptions import BrainCostCapError


class CostTracker:
    def __init__(self, monthly_cap: float):
        self._cap = monthly_cap
        self._total = 0.0
        self._store = None
        self._current_month: str = datetime.date.today().strftime("%Y-%m")

    @property
    def total_this_month(self) -> float:
        return self._total

    @property
    def remaining(self) -> float:
        return max(0.0, self._cap - self._total)

    @property
    def should_alert(self) -> bool:
        return self._total >= self._cap * 0.8

    def record(self, cost: float) -> None:
        self._total += cost
        if self._store:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._persist())
            except RuntimeError:
                pass

    def check_budget(self, estimated_cost: float) -> None:
        if self._total + estimated_cost > self._cap:
            raise BrainCostCapError(
                f"Monthly cost cap exceeded: ${self._total:.2f} spent of ${self._cap:.2f} cap"
            )

    def reset(self) -> None:
        self._total = 0.0

    def load_persisted(self, total: float) -> None:
        self._total = total

    def set_store(self, store) -> None:
        self._store = store

    async def load_from_db(self, store) -> None:
        """Load persisted cost from database. Auto-resets if month changed."""
        self._store = store
        today_month = datetime.date.today().strftime("%Y-%m")
        row = await store.fetchone(
            "SELECT value FROM core_state WHERE key = 'cost_month'"
        )
        saved_month = row["value"] if row else None

        if saved_month == today_month:
            row = await store.fetchone(
                "SELECT value FROM core_state WHERE key = 'cost_total'"
            )
            if row:
                self._total = float(row["value"])
                self._current_month = today_month
        else:
            self._total = 0.0
            self._current_month = today_month
            await self._persist()

    async def _persist(self) -> None:
        if not self._store:
            return
        await self._store.execute(
            """INSERT INTO core_state (key, value) VALUES ('cost_total', ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (str(self._total),)
        )
        await self._store.execute(
            """INSERT INTO core_state (key, value) VALUES ('cost_month', ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (self._current_month,)
        )
