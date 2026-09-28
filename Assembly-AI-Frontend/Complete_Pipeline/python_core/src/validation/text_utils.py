"""Tiny generic helpers. No domain knowledge here."""

from __future__ import annotations

import re
from typing import Iterable


def alt(words: Iterable[str]) -> str:
    """Regex alternation of literal words, longest first ('sept|sep')."""
    return "|".join(re.escape(w) for w in sorted(set(words), key=len, reverse=True))


def fill(pattern: str, **tokens: str) -> str:
    """Replace <TOKEN> placeholders in a config pattern."""
    for name, value in tokens.items():
        pattern = pattern.replace(f"<{name}>", value)
    return pattern


def uniq(items: Iterable[str]) -> list[str]:
    """Remove duplicates, keep order."""
    return list(dict.fromkeys(items))
