"""Lazy, cached analysis of a text, shared by all checks (each fact computed once)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Optional

from .extractors import DateMatch, NegationState, Toolkit


class AnalyzedText:
    def __init__(self, text: str, tools: Toolkit, known_entities: Optional[list[str]] = None):
        self.text = text
        self._tools = tools
        self._known = known_entities or []

    @cached_property
    def dates(self) -> DateMatch:
        return self._tools.dates.extract(self.text)

    @cached_property
    def numbers(self) -> list[str]:
        # numbers are read from the text with dates removed ("Sept 15" is a date, not 15)
        return list(dict.fromkeys(self._tools.numbers.extract(self.dates.rest)))

    @cached_property
    def entities(self) -> list[str]:
        return self._tools.entities.extract(self.text, self._known)

    @cached_property
    def pronouns(self) -> list[str]:
        return self._tools.pronouns.extract(self.text)

    @cached_property
    def negation(self) -> NegationState:
        return self._tools.negation.state(self.text)

    @cached_property
    def tokens(self) -> list[str]:
        return self._tools.tokenizer.words(self.text)


@dataclass(frozen=True)
class Context:
    """Everything a check may look at."""

    original: AnalyzedText
    repaired: AnalyzedText
    has_correction_cue: bool

    @classmethod
    def build(cls, original: str, repaired: str, tools: Toolkit, known_entities=None) -> "Context":
        return cls(
            original=AnalyzedText(original, tools, known_entities),
            repaired=AnalyzedText(repaired, tools, known_entities),
            has_correction_cue=tools.corrections.found(original),
        )
