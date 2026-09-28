"""Reusable text extractors.

Each class does ONE job (find numbers, find dates, ...) and is configured only by
its own config section. They know nothing about validation, so any teammate can
reuse them, e.g. Person 2's analyzer:

    tools = Toolkit.from_config(load_config())
    tools.numbers.extract("I need five hundred dollars")   # ['500']
    tools.dates.extract("see you on September 15th").tokens  # ['sep 15']
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import NamedTuple, Optional

from .config import (
    CorrectionConfig,
    DateConfig,
    EntityConfig,
    NegationConfig,
    NumberConfig,
    TextConfig,
    ValidatorConfig,
)
from .text_utils import alt, fill, uniq


# ---------------------------------------------------------------------------
# Words
# ---------------------------------------------------------------------------
class Tokenizer:
    def __init__(self, cfg: TextConfig):
        self._word_re = re.compile(cfg.word_pattern)
        self._stem_re = re.compile(f"(?:{alt(cfg.stem_suffixes)})$")
        self._stem_min_length = int(cfg.stem_min_length)

    def words(self, text: str) -> list[str]:
        return self._word_re.findall(text.lower())

    def stem(self, word: str) -> str:
        return self._stem_re.sub("", word) if len(word) >= self._stem_min_length else word


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------
class _NumberBuilder:
    """Accumulates spoken numbers: 'five hundred and fifty' -> 550."""

    def __init__(self, hundred_value: int):
        self.hundred_value = hundred_value
        self.results: list[str] = []
        self._reset()

    def _reset(self) -> None:
        self.current = 0
        self.total = 0
        self.active = False
        self.last: Optional[str] = None  # "unit" | "tens" | "scale"

    def flush(self) -> None:
        if self.active:
            self.results.append(str(self.total + self.current))
        self._reset()

    def add_unit(self, value: int) -> None:
        if self.last == "unit":  # "five five" is a stutter, not 10
            self.flush()
        self.current += value
        self.active, self.last = True, "unit"

    def add_tens(self, value: int) -> None:
        if self.last in ("unit", "tens"):
            self.flush()
        self.current += value
        self.active, self.last = True, "tens"

    def add_hundred(self) -> None:
        if not self.active:
            self.current, self.active = 1, True
        self.current *= self.hundred_value
        self.last = "scale"

    def add_scale(self, value: int) -> None:
        self.total += (self.current or 1) * value
        self.current = 0
        self.active, self.last = True, "scale"


class NumberExtractor:
    """Finds numbers written as digits ('5,000') or words ('five thousand')."""

    def __init__(self, cfg: NumberConfig, tokenizer: Tokenizer):
        self._cfg = cfg
        self._tokenizer = tokenizer
        self._units = {k.lower(): int(v) for k, v in cfg.units.items()}
        self._tens = {k.lower(): int(v) for k, v in cfg.tens.items()}
        self._scales = {k.lower(): int(v) for k, v in cfg.scales.items()}
        self._hundred = cfg.hundred_word.lower()
        self._connectors = {w.lower() for w in cfg.connectors}
        self._digits_re = re.compile(cfg.pattern)
        self.number_words = frozenset(
            {*self._units, *self._tens, *self._scales, self._hundred}
        )

    def extract(self, text: str) -> list[str]:
        digits, rest = self._extract_digits(text)
        return digits + self._extract_words(rest)

    def _extract_digits(self, text: str) -> tuple[list[str], str]:
        found: list[str] = []

        def grab(m: re.Match) -> str:
            value = float(m.group(0).replace(self._cfg.thousands_separator, ""))
            found.append(str(int(value)) if value.is_integer() else str(value))
            return " "

        return found, self._digits_re.sub(grab, text)

    def _extract_words(self, text: str) -> list[str]:
        text = text.lower()
        for sep in self._cfg.word_separators:
            text = text.replace(sep, " ")
        words = self._tokenizer.words(text)
        builder = _NumberBuilder(int(self._cfg.hundred_value))

        for i, w in enumerate(words):
            following = words[i + 1] if i + 1 < len(words) else None
            if w in self._units:
                builder.add_unit(self._units[w])
            elif w in self._tens:
                builder.add_tens(self._tens[w])
            elif w == self._hundred:
                builder.add_hundred()
            elif w in self._scales:
                builder.add_scale(self._scales[w])
            elif w in self._connectors and builder.active and following in self.number_words:
                continue
            else:
                builder.flush()
        builder.flush()
        return builder.results


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------
class DateMatch(NamedTuple):
    tokens: list  # e.g. ['sep 15', 'friday']
    rest: str  # text with the dates removed (so '15' isn't also a number)


class DateExtractor:
    def __init__(self, cfg: DateConfig):
        self._key_length = int(cfg.month_key_length)
        months = [m.lower() for m in cfg.months]
        ambiguous = {m.lower() for m in cfg.ambiguous_months}
        tokens = {
            "MONTHS": alt(months + [m.lower() for m in cfg.month_abbreviations]),
            "SUFFIXES": alt(cfg.ordinal_suffixes),
        }
        standalone = (
            [m for m in months if m not in ambiguous]
            + [w.lower() for w in cfg.weekdays]
            + [w.lower() for w in cfg.relative_days]
        )
        self._month_day_re = re.compile(fill(cfg.month_day_pattern, **tokens))
        self._day_month_re = re.compile(fill(cfg.day_month_pattern, **tokens))
        self._numeric_re = re.compile(cfg.numeric_date_pattern)
        self._standalone_re = re.compile(fill(cfg.standalone_date_pattern, WORDS=alt(standalone)))
        self.words = frozenset(standalone) | frozenset(ambiguous)

    def extract(self, text: str) -> DateMatch:
        rest = text.lower()
        tokens: list[str] = []
        key = self._key_length

        def month_day(m: re.Match) -> str:
            tokens.append(f"{m.group(1)[:key]} {int(m.group(2))}")
            return " "

        def day_month(m: re.Match) -> str:
            tokens.append(f"{m.group(2)[:key]} {int(m.group(1))}")
            return " "

        def plain(m: re.Match) -> str:
            tokens.append(m.group(0))
            return " "

        rest = self._month_day_re.sub(month_day, rest)
        rest = self._day_month_re.sub(day_month, rest)
        rest = self._numeric_re.sub(plain, rest)
        rest = self._standalone_re.sub(plain, rest)
        return DateMatch(tokens, rest)


# ---------------------------------------------------------------------------
# Entities & pronouns
# ---------------------------------------------------------------------------
class EntityExtractor:
    """Capitalized non-sentence-start words + profile's known entities."""

    def __init__(self, cfg: EntityConfig, date_words):
        self._cfg = cfg
        self._date_words = date_words
        self._split_re = re.compile(cfg.sentence_split_pattern)
        self._strip_re = re.compile(cfg.strip_pattern)
        self._token_re = re.compile(cfg.token_pattern)
        self._first_person_re = re.compile(cfg.first_person_pattern)

    def extract(self, text: str, known: Optional[list[str]] = None) -> list[str]:
        found: set[str] = set()
        for sentence in self._split_re.split(text):
            for i, raw in enumerate(sentence.split()):
                token = self._strip_re.sub("", raw)
                if self._is_entity(token, is_sentence_start=(i == 0)):
                    found.add(token.lower())
        found.update(self._known_in(text, known or []))
        return sorted(found)

    def _is_entity(self, token: str, is_sentence_start: bool) -> bool:
        return (
            bool(token)
            and not is_sentence_start
            and not self._first_person_re.match(token)
            and bool(self._token_re.match(token))
            and token.lower() not in self._date_words  # dates have their own check
        )

    def _known_in(self, text: str, known: list[str]) -> list[str]:
        lower = text.lower()
        hits = []
        for name in known:
            name = name.strip().lower()
            if name and re.search(fill(self._cfg.known_entity_pattern, ENTITY=re.escape(name)), lower):
                hits.append(name)
        return hits


class PronounExtractor:
    def __init__(self, cfg: EntityConfig, tokenizer: Tokenizer):
        self._tokenizer = tokenizer
        self._pronouns = {p.lower() for p in cfg.pronouns}

    def extract(self, text: str) -> list[str]:
        return uniq(w for w in self._tokenizer.words(text) if w in self._pronouns)


# ---------------------------------------------------------------------------
# Negation & self-correction
# ---------------------------------------------------------------------------
class NegationState(NamedTuple):
    strong: bool  # not / never / n't ...
    weak: bool  # "no money" (but NOT "Friday, no Wednesday")


class NegationDetector:
    def __init__(self, cfg: NegationConfig, date_words, number_words):
        parts = [fill(cfg.strong_pattern, WORDS=alt(cfg.words))]
        if cfg.contraction_suffixes:
            parts.append(fill(cfg.contraction_pattern, SUFFIXES=alt(cfg.contraction_suffixes)))
        self._strong_re = re.compile("|".join(parts), re.I)
        self._weak_re = re.compile(fill(cfg.weak_pattern, WORD=re.escape(cfg.weak_word)), re.I)
        self._not_a_noun = {w.lower() for w in cfg.weak_exclusions} | set(date_words) | set(number_words)

    def state(self, text: str) -> NegationState:
        return NegationState(bool(self._strong_re.search(text)), self._has_weak(text))

    def _has_weak(self, text: str) -> bool:
        return any(m.group(1).lower() not in self._not_a_noun for m in self._weak_re.finditer(text))


class CorrectionCueDetector:
    """Did the speaker correct themselves? ('Friday... actually Wednesday')"""

    def __init__(self, cfg: CorrectionConfig):
        self._re = re.compile(fill(cfg.pattern, WORDS=alt(cfg.cues)), re.I)

    def found(self, text: str) -> bool:
        return bool(self._re.search(text))


# ---------------------------------------------------------------------------
# Everything together
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Toolkit:
    tokenizer: Tokenizer
    numbers: NumberExtractor
    dates: DateExtractor
    entities: EntityExtractor
    pronouns: PronounExtractor
    negation: NegationDetector
    corrections: CorrectionCueDetector

    @classmethod
    def from_config(cls, cfg: ValidatorConfig) -> "Toolkit":
        tokenizer = Tokenizer(cfg.text)
        numbers = NumberExtractor(cfg.numbers, tokenizer)
        dates = DateExtractor(cfg.dates)
        return cls(
            tokenizer=tokenizer,
            numbers=numbers,
            dates=dates,
            entities=EntityExtractor(cfg.entities, dates.words),
            pronouns=PronounExtractor(cfg.entities, tokenizer),
            negation=NegationDetector(cfg.negation, dates.words, numbers.number_words),
            corrections=CorrectionCueDetector(cfg.correction),
        )
