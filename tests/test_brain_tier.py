from pa.brain.tier import classify_tier, Tier


def test_balance_query_routes_to_haiku():
    assert classify_tier("what's my Chase balance?") == Tier.FAST
    assert classify_tier("how much money do I have?") == Tier.FAST


def test_status_query_routes_to_haiku():
    assert classify_tier("what's the status?") == Tier.FAST
    assert classify_tier("when is my payment due?") == Tier.FAST


def test_spending_query_routes_to_sonnet():
    assert classify_tier("what did I spend this month?") == Tier.STANDARD
    assert classify_tier("show me spending by category") == Tier.STANDARD
    assert classify_tier("compare my spending to last month") == Tier.STANDARD


def test_strategy_query_routes_to_opus():
    assert classify_tier("build me a debt payoff plan") == Tier.DEEP
    assert classify_tier("what's the best strategy to save money?") == Tier.DEEP
    assert classify_tier("create a monthly budget for me") == Tier.DEEP
    assert classify_tier("give me financial advice") == Tier.DEEP


def test_unknown_query_defaults_to_sonnet():
    assert classify_tier("hello there") == Tier.STANDARD
    assert classify_tier("what is the weather") == Tier.STANDARD
