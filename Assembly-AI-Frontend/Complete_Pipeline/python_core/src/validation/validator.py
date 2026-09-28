"""MeaningValidator: runs the configured checks, in order, and returns a verdict."""

from __future__ import annotations

from functools import lru_cache
from typing import Optional, Sequence

from ._contracts import ValidationResult
from .analysis import Context
from .checks import Check, build_checks
from .config import ValidatorConfig, load_config
from .extractors import Toolkit
from .guard import Guard
from .verdict import Verdict


class MeaningValidator:
    """Build ONCE (startup), reuse for every utterance.

        validator = MeaningValidator()
        result = validator.validate(original, repaired, known_entities=[...])
        text = repaired if result["approved"] else original
    """

    def __init__(self, config: Optional[ValidatorConfig] = None, checks: Optional[Sequence[Check]] = None):
        self.config = config or load_config()
        self.tools = Toolkit.from_config(self.config)
        self._guard = Guard(self.config)
        self._checks = (
            list(checks) if checks is not None
            else build_checks(self.config.checks, self.tools, self.config)
        )

    def check(self, original: str, repaired: str, known_entities: Optional[list[str]] = None) -> Verdict:
        """Full verdict (reason + detail)."""
        early = self._guard.inspect(original, repaired)
        if early is not None:
            return early

        ctx = Context.build(original.strip(), repaired.strip(), self.tools, known_entities)
        for check in self._checks:
            detail = check.run(ctx)
            if detail is not None:
                return Verdict.reject(check.reason, detail)
        return Verdict.approve()

    def validate(self, original: str, repaired: str, known_entities: Optional[list[str]] = None) -> ValidationResult:
        """The frozen team contract: {"approved": bool, "reason": str}."""
        return self.check(original, repaired, known_entities).to_result()

    def validate_with_detail(self, original: str, repaired: str, known_entities: Optional[list[str]] = None) -> dict:
        """Contract + a `detail` string, for logs / metrics."""
        return self.check(original, repaired, known_entities).to_dict()


@lru_cache(maxsize=1)
def get_default_validator() -> MeaningValidator:
    return MeaningValidator()


def validate(original: str, repaired: str, known_entities: Optional[list[str]] = None) -> ValidationResult:
    """Shortcut using the default config."""
    return get_default_validator().validate(original, repaired, known_entities)


def validate_with_detail(original: str, repaired: str, known_entities: Optional[list[str]] = None) -> dict:
    return get_default_validator().validate_with_detail(original, repaired, known_entities)
