"""Privacy scrubbing for prompts sent to untrusted (cloud) LLM backends.

scrub() replaces sensitive tokens with stable placeholders and returns a
restore map; restore() re-substitutes them in the model's response. Stable
placeholders (same input -> same placeholder within a call) keep the text
coherent for the model.
"""
from __future__ import annotations

import re

# Order matters: more specific patterns first so e.g. card numbers aren't
# half-eaten by the account-number rule.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("PHONE", re.compile(r"\b(?:\+1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b")),
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    # Account fragments like "····1234" / "x1234" / "ending in 1234"
    ("ACCT", re.compile(r"(?:·+|\*+|x{1,2}|ending in )\s?\d{4}\b", re.IGNORECASE)),
]


def scrub(text: str) -> tuple[str, dict[str, str]]:
    """Replace sensitive tokens with placeholders. Returns (clean, restore_map)."""
    restore: dict[str, str] = {}
    seen: dict[str, str] = {}

    def _sub_factory(label: str):
        def _sub(m: re.Match) -> str:
            original = m.group(0)
            if original in seen:
                return seen[original]
            placeholder = f"[{label}_{len([k for k in restore if k.startswith('[' + label + '_')]) + 1}]"
            restore[placeholder] = original
            seen[original] = placeholder
            return placeholder
        return _sub

    clean = text
    for label, pattern in _PATTERNS:
        clean = pattern.sub(_sub_factory(label), clean)
    return clean, restore


def restore(text: str, restore_map: dict[str, str]) -> str:
    """Re-substitute placeholders the model echoed back."""
    for placeholder, original in restore_map.items():
        text = text.replace(placeholder, original)
    return text
