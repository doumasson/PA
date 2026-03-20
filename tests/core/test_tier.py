from pa.core.tier import Tier, TierClassifier

def test_default_returns_standard():
    tc = TierClassifier()
    assert tc.classify("hello world") == Tier.STANDARD

def test_register_and_match_fast():
    tc = TierClassifier()
    tc.register({"fast": [r"\bbalance\b"], "standard": [], "deep": []})
    assert tc.classify("show my balance") == Tier.FAST

def test_register_and_match_deep():
    tc = TierClassifier()
    tc.register({"fast": [], "standard": [], "deep": [r"\bstrategy\b"]})
    assert tc.classify("debt payoff strategy") == Tier.DEEP

def test_deep_takes_priority():
    tc = TierClassifier()
    tc.register({"fast": [r"\bbalance\b"], "standard": [], "deep": [r"\bbalance\b"]})
    assert tc.classify("balance strategy") == Tier.DEEP

def test_multiple_registrations_merge():
    tc = TierClassifier()
    tc.register({"fast": [r"\bfoo\b"], "standard": [], "deep": []})
    tc.register({"fast": [r"\bbar\b"], "standard": [], "deep": []})
    assert tc.classify("foo") == Tier.FAST
    assert tc.classify("bar") == Tier.FAST
