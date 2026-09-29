"""P3.2 Fallback Engine: LLM output -> safer output -> original transcript.

    engine = FallbackEngine(validator)
    decision = engine.resolve(original_text, repaired_text)
    speak(decision.text)            # decision.source says which level won

The "safer" level is built from the ORIGINAL transcript (never from the LLM
output), by removing only fillers and stutters of configured words. So if the LLM
turns 500 into 5,000, the listener can never hear 5,000.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from src.common import ConfigError, load_json_config

from .text_utils import alt, fill
from .validator import MeaningValidator

DEFAULT_FALLBACK_CONFIG_PATH = Path(__file__).with_name("fallback_config.json")
FALLBACK_CONFIG_ENV_VAR = "CLEARVOICE_FALLBACK_CONFIG"


@dataclass(frozen=True)
class SaferConfig:
    fillers: list
    stutter_words: list
    filler_pattern: str
    repeat_pattern: str


@dataclass(frozen=True)
class FallbackConfig:
    hierarchy: list
    trusted_levels: list
    safer: SaferConfig


def load_fallback_config(path=None) -> FallbackConfig:
    return load_json_config(FallbackConfig, DEFAULT_FALLBACK_CONFIG_PATH, FALLBACK_CONFIG_ENV_VAR, path)


# ---------------------------------------------------------------------------
# Conservative rewriter (fillers + stutters only)
# ---------------------------------------------------------------------------
class SaferRewriter:
    """Deterministic minimal cleanup. Reusable on its own (e.g. as a mock LLM)."""

    def __init__(self, cfg: SaferConfig):
        flags = re.I
        self._filler_re = (
            re.compile(fill(cfg.filler_pattern, WORDS=alt(cfg.fillers)), flags) if cfg.fillers else None
        )
        self._repeat_re = (
            re.compile(fill(cfg.repeat_pattern, WORDS=alt(cfg.stutter_words)), flags)
            if cfg.stutter_words else None
        )

    def rewrite(self, text: str) -> str:
        if self._filler_re:
            text = self._filler_re.sub("", text)
        if self._repeat_re:
            text = self._repeat_re.sub(lambda m: m.group(1), text)
        return " ".join(text.split())


# ---------------------------------------------------------------------------
# Decision objects
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Attempt:
    level: str
    skipped: bool = False
    reason: Optional[str] = None  # validator reason when the candidate was checked


@dataclass(frozen=True)
class FallbackDecision:
    text: str
    source: str  # which level won
    attempts: list = field(default_factory=list)

    @property
    def rejected(self) -> list:
        """Attempts that were checked and refused."""
        return [a for a in self.attempts if not a.skipped and a.level != self.source]


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
class FallbackEngine:
    def __init__(self, validator: MeaningValidator, config: Optional[FallbackConfig] = None):
        self._validator = validator
        self.config = config or load_fallback_config()
        self._rewriter = SaferRewriter(self.config.safer)
        # level name -> function(original, repaired) -> candidate text or None (not applicable)
        self._producers: dict[str, Callable[[str, Optional[str]], Optional[str]]] = {
            "repaired": self._from_repaired,
            "safer": self._from_safer,
            "original": lambda original, repaired: original,
        }
        unknown = [lv for lv in self.config.hierarchy if lv not in self._producers]
        if unknown:
            raise ConfigError(f"Unknown fallback level(s) {unknown}. Available: {sorted(self._producers)}")
        if not any(lv in self.config.trusted_levels for lv in self.config.hierarchy):
            raise ConfigError("Fallback hierarchy needs at least one trusted level (e.g. 'original').")

    @property
    def rewriter(self) -> SaferRewriter:
        return self._rewriter

    def resolve(
        self, original: str, repaired: Optional[str], known_entities: Optional[list[str]] = None
    ) -> FallbackDecision:
        original = (original or "").strip()
        attempts: list[Attempt] = []

        for level in self.config.hierarchy:
            candidate = self._producers[level](original, repaired)
            if candidate is None:
                attempts.append(Attempt(level, skipped=True))
                continue
            if level in self.config.trusted_levels:
                attempts.append(Attempt(level))
                return FallbackDecision(candidate, level, attempts)
            verdict = self._validator.check(original, candidate, known_entities)
            attempts.append(Attempt(level, reason=verdict.reason))
            if verdict.approved:
                return FallbackDecision(candidate.strip(), level, attempts)

        raise ConfigError("No fallback level produced a result")  # unreachable: init guarantees a trusted level

    # ---- producers -------------------------------------------------------
    @staticmethod
    def _from_repaired(original: str, repaired: Optional[str]) -> Optional[str]:
        return repaired if isinstance(repaired, str) and repaired.strip() else None

    def _from_safer(self, original: str, repaired: Optional[str]) -> Optional[str]:
        cleaned = self._rewriter.rewrite(original)
        return cleaned if cleaned and cleaned != original else None  # unchanged == just the original
