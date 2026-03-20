import re
from enum import Enum


class Tier(Enum):
    FAST = "haiku"
    STANDARD = "sonnet"
    DEEP = "opus"


class TierClassifier:
    def __init__(self):
        self._patterns: dict[Tier, list[str]] = {
            Tier.FAST: [], Tier.STANDARD: [], Tier.DEEP: [],
        }

    def register(self, patterns: dict[str, list[str]]) -> None:
        for tier_name, pattern_list in patterns.items():
            tier = Tier[tier_name.upper()]
            self._patterns[tier].extend(pattern_list)

    def classify(self, query: str) -> Tier:
        lower = query.lower()
        for pattern in self._patterns[Tier.DEEP]:
            if re.search(pattern, lower):
                return Tier.DEEP
        for pattern in self._patterns[Tier.STANDARD]:
            if re.search(pattern, lower):
                return Tier.STANDARD
        for pattern in self._patterns[Tier.FAST]:
            if re.search(pattern, lower):
                return Tier.FAST
        return Tier.STANDARD
