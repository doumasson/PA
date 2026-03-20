import re
from enum import Enum


class Tier(Enum):
    FAST = "haiku"
    STANDARD = "sonnet"
    DEEP = "opus"


_FAST_PATTERNS = [
    r"\bbalance\b", r"\bhow much\b", r"\bstatus\b", r"\bdue\b",
    r"\bowed?\b", r"\bminimum\b", r"\btotal\b", r"\bremaining\b",
]

_DEEP_PATTERNS = [
    r"\bplan\b", r"\bstrategy\b", r"\bbudget\b", r"\bpayoff\b",
    r"\badvice\b", r"\brecommend\b", r"\boptimize\b", r"\bsnowball\b",
    r"\bavalanche\b", r"\bgoal\b", r"\bsave money\b", r"\bget out of debt\b",
]

_STANDARD_PATTERNS = [
    r"\bspend", r"\bcategory\b", r"\bcompare\b", r"\btrend\b",
    r"\bpattern\b", r"\banalyz", r"\bbreakdown\b", r"\bhistory\b",
]


def classify_tier(query: str) -> Tier:
    lower = query.lower()
    for pattern in _DEEP_PATTERNS:
        if re.search(pattern, lower):
            return Tier.DEEP
    for pattern in _STANDARD_PATTERNS:
        if re.search(pattern, lower):
            return Tier.STANDARD
    for pattern in _FAST_PATTERNS:
        if re.search(pattern, lower):
            return Tier.FAST
    return Tier.STANDARD
