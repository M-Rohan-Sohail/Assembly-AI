"""The individual validation checks.

A check answers ONE question about (original, repaired) and returns
  - None            -> looks fine
  - a detail string -> problem found (the check's `reason` is reported)

To add your own check:
    @register_check
    class MyCheck(Check):
        name = "my_check"                       # add this name to "checks" in the config
        reason = ValidationReason.SEMANTIC_RISK
        def run(self, ctx): ...                 # return None or a detail string
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, Optional, Sequence

from ._contracts import ValidationReason as R
from .analysis import AnalyzedText, Context
from .config import ValidatorConfig
from .extractors import Toolkit
from .text_utils import uniq


# ---------------------------------------------------------------------------
# Base class + registry
# ---------------------------------------------------------------------------
class Check(ABC):
    name: ClassVar[str]  # key used in the config's "checks" list
    reason: ClassVar[str]  # ValidationReason reported when this check fails

    def __init__(self, tools: Toolkit, config: ValidatorConfig):
        self.tools = tools
        self.config = config

    @abstractmethod
    def run(self, ctx: Context) -> Optional[str]:
        """Return None if OK, or a detail message if the check fails."""


_REGISTRY: dict[str, type[Check]] = {}


def register_check(cls: type[Check]) -> type[Check]:
    _REGISTRY[cls.name] = cls
    return cls


def available_checks() -> list[str]:
    return sorted(_REGISTRY)


def build_checks(names: Sequence[str], tools: Toolkit, config: ValidatorConfig) -> list[Check]:
    unknown = [n for n in names if n not in _REGISTRY]
    if unknown:
        raise ValueError(f"Unknown check(s) {unknown}. Available: {available_checks()}")
    return [_REGISTRY[n](tools, config) for n in names]


# ---------------------------------------------------------------------------
# "Nothing invented, nothing silently lost" checks (dates / numbers / entities)
# ---------------------------------------------------------------------------
def is_preserved(before: Sequence[str], after: Sequence[str], has_cue: bool) -> bool:
    """1. Nothing new may appear.
    2. If there was something, at least one must remain.
    3. Dropping a value needs a self-correction cue ('Friday... actually Thursday').
    """
    b, a = set(before), set(after)
    if not a <= b:
        return False
    if b and not a:
        return False
    if not has_cue and not b <= a:
        return False
    return True


class PreservationCheck(Check):
    """Base for checks that compare a list of values found in both texts."""

    @abstractmethod
    def values(self, text: AnalyzedText) -> list[str]:
        ...

    def run(self, ctx: Context) -> Optional[str]:
        before, after = self.values(ctx.original), self.values(ctx.repaired)
        if is_preserved(before, after, ctx.has_correction_cue):
            return None
        return self.config.message("changed", before=before, after=after)


@register_check
class DateCheck(PreservationCheck):
    name = "dates"
    reason = R.DATE_CHANGED

    def values(self, text: AnalyzedText) -> list[str]:
        return text.dates.tokens


@register_check
class NumberCheck(PreservationCheck):
    name = "numbers"
    reason = R.NUMBER_CHANGED

    def values(self, text: AnalyzedText) -> list[str]:
        return text.numbers


@register_check
class EntityCheck(PreservationCheck):
    name = "entities"
    reason = R.ENTITY_CHANGED

    def values(self, text: AnalyzedText) -> list[str]:
        return text.entities


# ---------------------------------------------------------------------------
# Other checks
# ---------------------------------------------------------------------------
@register_check
class PronounCheck(Check):
    """'him' -> 'her' changes who the sentence is about."""

    name = "pronouns"
    reason = R.ENTITY_CHANGED

    def run(self, ctx: Context) -> Optional[str]:
        added = [p for p in ctx.repaired.pronouns if p not in ctx.original.pronouns]
        return self.config.message("new_pronouns", items=added) if added else None


@register_check
class NegationCheck(Check):
    name = "negation"
    reason = R.NEGATION_CHANGED

    def run(self, ctx: Context) -> Optional[str]:
        before, after = ctx.original.negation, ctx.repaired.negation
        if before == after:
            return None
        return self.config.message("changed", before=before, after=after)


@register_check
class SemanticRiskCheck(Check):
    """Generic 'did the LLM invent or throw away too much?' safety net."""

    name = "semantic_risk"
    reason = R.SEMANTIC_RISK

    def __init__(self, tools: Toolkit, config: ValidatorConfig):
        super().__init__(tools, config)
        self._function_words = {w.lower() for w in config.semantic.function_words}

    def run(self, ctx: Context) -> Optional[str]:
        return self._new_vocabulary(ctx) or self._too_short(ctx) or self._too_long(ctx)

    def _new_vocabulary(self, ctx: Context) -> Optional[str]:
        cfg, stem = self.config.semantic, self.tools.tokenizer.stem
        known = {stem(w) for w in ctx.original.tokens}
        content = [w for w in ctx.repaired.tokens if w not in self._function_words]
        novel = uniq(stem(w) for w in content if stem(w) not in known)
        ratio = len(novel) / max(len(content), 1)
        too_many = len(novel) >= cfg.max_novel_words
        too_dense = len(novel) >= cfg.min_novel_words_for_ratio and ratio > cfg.novel_word_ratio
        return self.config.message("new_words", items=novel) if too_many or too_dense else None

    def _too_short(self, ctx: Context) -> Optional[str]:
        cfg = self.config.semantic
        before, after = len(ctx.original.tokens), len(ctx.repaired.tokens)
        if before >= cfg.shrink_min_tokens and after < before * cfg.shrink_ratio:
            return self.config.message("too_short")
        return None

    def _too_long(self, ctx: Context) -> Optional[str]:
        cfg = self.config.semantic
        before, after = len(ctx.original.tokens), len(ctx.repaired.tokens)
        if after > before * cfg.growth_factor + cfg.growth_extra_tokens:
            return self.config.message("too_long")
        return None
