from pa.core.cost_tracker import CostTracker
from pa.core.exceptions import BrainCostCapError
import pytest


def test_initial_state():
    ct = CostTracker(monthly_cap=20.0)
    assert ct.total_this_month == 0.0
    assert ct.remaining == 20.0


def test_record():
    ct = CostTracker(monthly_cap=20.0)
    ct.record(5.0)
    assert ct.total_this_month == 5.0
    assert ct.remaining == 15.0


def test_alert_at_80_percent():
    ct = CostTracker(monthly_cap=10.0)
    ct.record(8.0)
    assert ct.should_alert


def test_check_budget_raises():
    ct = CostTracker(monthly_cap=10.0)
    ct.record(9.5)
    with pytest.raises(BrainCostCapError):
        ct.check_budget(1.0)


def test_reset():
    ct = CostTracker(monthly_cap=10.0)
    ct.record(5.0)
    ct.reset()
    assert ct.total_this_month == 0.0
