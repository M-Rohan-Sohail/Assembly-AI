"""First gate: catches broken input before any real checking starts."""

from __future__ import annotations

import re
from typing import Optional

from ._contracts import ValidationReason as R
from .config import ValidatorConfig
from .verdict import Verdict


class Guard:
    def __init__(self, config: ValidatorConfig):
        self._config = config
        patterns = config.guard.invalid_output_patterns
        self._invalid_re = re.compile("|".join(f"(?:{p})" for p in patterns), re.I) if patterns else None

    def inspect(self, original: object, repaired: object) -> Optional[Verdict]:
        """A final Verdict if no further checking is needed, else None."""
        msg = self._config.message
        if not isinstance(original, str) or not isinstance(repaired, str):
            return Verdict.reject(R.INVALID_OUTPUT, msg("non_string"))
        original, repaired = original.strip(), repaired.strip()
        if not repaired:
            return Verdict.reject(R.INVALID_OUTPUT, msg("empty_output"))
        if not original:
            return Verdict.reject(R.INVALID_OUTPUT, msg("empty_original"))
        if self._invalid_re and self._invalid_re.search(repaired):
            return Verdict.reject(R.INVALID_OUTPUT, msg("llm_chatter"))
        if repaired == original:
            return Verdict.approve()
        return None
