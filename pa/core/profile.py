"""Family profile — everything personal lives in config, never in code."""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Kid:
    name: str
    birth_year: int | None = None
    birth_date: str | None = None  # ISO YYYY-MM-DD; preferred over birth_year
    notes: str = ""

    def age(self, today: datetime.date | None = None) -> int | None:
        today = today or datetime.date.today()
        if self.birth_date:
            try:
                born = datetime.date.fromisoformat(self.birth_date)
                had_birthday = (today.month, today.day) >= (born.month, born.day)
                return today.year - born.year - (0 if had_birthday else 1)
            except ValueError:
                pass
        if self.birth_year is None:
            return None
        return today.year - self.birth_year


@dataclass
class Profile:
    owner: str = "the user"
    timezone: str = "UTC"
    kids: list[Kid] = field(default_factory=list)
    monthly_income: float | None = None
    goals: list[str] = field(default_factory=list)

    @classmethod
    def from_config(cls, data: dict[str, Any] | None) -> "Profile":
        data = data or {}
        kids = [
            Kid(
                name=k.get("name", "").strip(),
                birth_year=k.get("birth_year"),
                birth_date=k.get("birth_date"),
                notes=k.get("notes", ""),
            )
            for k in data.get("kids", [])
            if k.get("name")
        ]
        return cls(
            owner=data.get("owner", "the user"),
            timezone=data.get("timezone", "UTC"),
            kids=kids,
            monthly_income=data.get("monthly_income"),
            goals=list(data.get("goals", [])),
        )

    def kid(self, name: str) -> Kid | None:
        name = name.strip().lower()
        for k in self.kids:
            if k.name.lower() == name:
                return k
        return None

    def system_prompt_fragment(self) -> str:
        parts = [f"You assist {self.owner}."]
        if self.kids:
            kid_bits = []
            for k in self.kids:
                age = k.age()
                desc = k.name + (f" ({age})" if age is not None else "")
                if k.notes:
                    desc += f" — {k.notes}"
                kid_bits.append(desc)
            parts.append("Kids: " + "; ".join(kid_bits) + ".")
        if self.goals:
            parts.append("Goals: " + "; ".join(self.goals) + ".")
        parts.append(f"Timezone: {self.timezone}.")
        return " ".join(parts)
