from pa.exceptions import BrainCostCapError


class CostTracker:
    def __init__(self, monthly_cap: float):
        self._cap = monthly_cap
        self._total = 0.0

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

    def check_budget(self, estimated_cost: float) -> None:
        if self._total + estimated_cost > self._cap:
            raise BrainCostCapError(
                f"Monthly cost cap exceeded: ${self._total:.2f} spent of ${self._cap:.2f} cap"
            )

    def reset(self) -> None:
        self._total = 0.0

    def load_persisted(self, total: float) -> None:
        """Load previously persisted cost total (e.g., from database on startup)."""
        self._total = total
