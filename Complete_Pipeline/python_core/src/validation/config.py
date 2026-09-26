"""Validator configuration: typed sections loaded from validator_config.json.

Nothing domain-specific lives in code - word lists, regex patterns, thresholds,
check order and messages all come from the JSON. Each section below is consumed
by exactly one extractor / check, so a teammate only needs to read one section.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Optional

# Bootstrap only: where to find the config.
DEFAULT_CONFIG_PATH = Path(__file__).with_name("validator_config.json")
CONFIG_ENV_VAR = "CLEARVOICE_VALIDATOR_CONFIG"


@dataclass(frozen=True)
class TextConfig:
    word_pattern: str
    stem_suffixes: list
    stem_min_length: int


@dataclass(frozen=True)
class NumberConfig:
    units: dict
    tens: dict
    scales: dict
    hundred_word: str
    hundred_value: int
    connectors: list
    pattern: str
    thousands_separator: str
    word_separators: list


@dataclass(frozen=True)
class DateConfig:
    months: list
    month_abbreviations: list
    ambiguous_months: list
    weekdays: list
    relative_days: list
    ordinal_suffixes: list
    month_key_length: int
    month_day_pattern: str
    day_month_pattern: str
    numeric_date_pattern: str
    standalone_date_pattern: str


@dataclass(frozen=True)
class EntityConfig:
    sentence_split_pattern: str
    strip_pattern: str
    token_pattern: str
    first_person_pattern: str
    known_entity_pattern: str
    pronouns: list


@dataclass(frozen=True)
class NegationConfig:
    words: list
    contraction_suffixes: list
    strong_pattern: str
    contraction_pattern: str
    weak_word: str
    weak_pattern: str
    weak_exclusions: list


@dataclass(frozen=True)
class CorrectionConfig:
    cues: list
    pattern: str


@dataclass(frozen=True)
class GuardConfig:
    invalid_output_patterns: list


@dataclass(frozen=True)
class SemanticConfig:
    function_words: list
    max_novel_words: int
    novel_word_ratio: float
    min_novel_words_for_ratio: int
    shrink_min_tokens: int
    shrink_ratio: float
    growth_factor: float
    growth_extra_tokens: int


_SECTION_TYPES = {
    "text": TextConfig,
    "numbers": NumberConfig,
    "dates": DateConfig,
    "entities": EntityConfig,
    "negation": NegationConfig,
    "correction": CorrectionConfig,
    "guard": GuardConfig,
    "semantic": SemanticConfig,
}


def _clean(data: dict) -> dict:
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _check_keys(cls, data: dict, where: str) -> None:
    names = {f.name for f in fields(cls)}
    missing = sorted(names - data.keys())
    unknown = sorted(data.keys() - names)
    if missing or unknown:
        raise ValueError(
            f"Invalid validator config [{where}]. Missing keys: {missing}. Unknown keys: {unknown}."
        )


@dataclass(frozen=True)
class ValidatorConfig:
    checks: list  # names of checks to run, in order
    text: TextConfig
    numbers: NumberConfig
    dates: DateConfig
    entities: EntityConfig
    negation: NegationConfig
    correction: CorrectionConfig
    guard: GuardConfig
    semantic: SemanticConfig
    messages: dict

    @classmethod
    def from_dict(cls, data: dict) -> "ValidatorConfig":
        data = _clean(data)
        _check_keys(cls, data, "top level")
        parts = {}
        for f in fields(cls):
            value = data[f.name]
            if f.name in _SECTION_TYPES:
                section = _clean(value)
                _check_keys(_SECTION_TYPES[f.name], section, f.name)
                value = _SECTION_TYPES[f.name](**section)
            parts[f.name] = value
        return cls(**parts)

    def override(self, section: str, **changes) -> "ValidatorConfig":
        """Copy with some values of one section changed (tests / tuning)."""
        return replace(self, **{section: replace(getattr(self, section), **changes)})

    def message(self, key: str, **kwargs) -> str:
        return self.messages[key].format(**kwargs)


def load_config(path: Optional[str | os.PathLike] = None) -> ValidatorConfig:
    """Load config from `path`, else $CLEARVOICE_VALIDATOR_CONFIG, else the default JSON."""
    chosen = Path(path or os.environ.get(CONFIG_ENV_VAR) or DEFAULT_CONFIG_PATH)
    with open(chosen, encoding="utf-8") as fh:
        return ValidatorConfig.from_dict(json.load(fh))
