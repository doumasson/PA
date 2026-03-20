import pytest

from pa.brain.cost_tracker import CostTracker
from pa.exceptions import BrainCostCapError


def test_record_and_get_total():
    tracker = CostTracker(monthly_cap=20.0)
    tracker.record(0.05)
    tracker.record(0.10)
    assert tracker.total_this_month == pytest.approx(0.15)


def test_cap_exceeded_raises():
    tracker = CostTracker(monthly_cap=1.0)
    tracker.record(0.80)
    tracker.record(0.15)
    with pytest.raises(BrainCostCapError):
        tracker.check_budget(estimated_cost=0.10)


def test_under_cap_does_not_raise():
    tracker = CostTracker(monthly_cap=20.0)
    tracker.record(5.0)
    tracker.check_budget(estimated_cost=0.10)


def test_alert_at_80_percent():
    tracker = CostTracker(monthly_cap=10.0)
    tracker.record(8.0)
    assert tracker.should_alert


def test_no_alert_under_80_percent():
    tracker = CostTracker(monthly_cap=10.0)
    tracker.record(7.0)
    assert not tracker.should_alert


def test_reset_clears_total():
    tracker = CostTracker(monthly_cap=20.0)
    tracker.record(10.0)
    tracker.reset()
    assert tracker.total_this_month == 0.0


def test_remaining_budget():
    tracker = CostTracker(monthly_cap=20.0)
    tracker.record(5.0)
    assert tracker.remaining == pytest.approx(15.0)


def test_load_from_persisted():
    tracker = CostTracker(monthly_cap=20.0)
    tracker.load_persisted(7.5)
    assert tracker.total_this_month == pytest.approx(7.5)
