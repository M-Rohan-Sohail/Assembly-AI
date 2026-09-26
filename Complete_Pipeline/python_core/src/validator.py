"""ClearVoice 2.0 - P3.1 Meaning Validator (Python).

Fully deterministic (no LLM). Compares the ORIGINAL transcript with the LLM's
REPAIRED text.

Core idea: the LLM may DELETE stutters / fillers / restarts, but it may never
INVENT or CHANGE numbers, dates, entities, pronouns or negation.

NOTHING is hardcoded here. Word lists, regex patterns, thresholds and messages
all live in `validator_config.json`; the reason names live in contracts.py
(`ValidationReason`). To tune behaviour or support another language, edit the
JSON or point CLEARVOICE_VALIDATOR_CONFIG to a different file.

Usage (from the orchestrator) - build ONCE, reuse for every utterance:
    from src.validator import MeaningValidator
    validator = MeaningValidator()
    result = validator.validate(repair["original_text"], repair["repaired_text"],
                                known_entities=profile.get("known_entities"))
    text = repair["repaired_text"] if result["approved"] else repair["original_text"]
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, fields, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

try:  # works whether the project is run from the repo root or from src/
    from src.contracts import ValidationReason as R
    from src.contracts import ValidationResult
except ImportError:  # pragma: no cover
    from contracts import ValidationReason as R
    from contracts import ValidationResult

# Bootstrap only: where to find the config.
DEFAULT_CONFIG_PATH = Path(__file__).with_name("validator_config.json")
CONFIG_ENV_VAR = "CLEARVOICE_VALIDATOR_CONFIG"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ValidatorConfig:
    # numbers
    number_units: Any
    number_tens: Any
    number_scales: Any
    number_hundred_word: Any
    number_hundred_value: Any
    number_connectors: Any
    number_pattern: Any
    thousands_separator: Any
    number_word_separators: Any
    word_pattern: Any
    # dates
    months: Any
    month_abbreviations: Any
    ambiguous_months: Any
    weekdays: Any
    relative_days: Any
    ordinal_suffixes: Any
    month_key_length: Any
    month_day_pattern: Any
    day_month_pattern: Any
    numeric_date_pattern: Any
    standalone_date_pattern: Any
    # entities / pronouns
    sentence_split_pattern: Any
    entity_strip_pattern: Any
    entity_token_pattern: Any
    first_person_pattern: Any
    known_entity_pattern: Any
    pronouns: Any
    # negation
    negation_words: Any
    negation_contraction_suffixes: Any
    strong_negation_pattern: Any
    negation_contraction_pattern: Any
    weak_negation_word: Any
    weak_negation_pattern: Any
    weak_negation_exclusions: Any
    # correction cues / invalid output
    correction_cues: Any
    correction_cue_pattern: Any
    invalid_output_patterns: Any
    # semantic risk
    function_words: Any
    stem_suffixes: Any
    stem_min_length: Any
    max_novel_words: Any
    novel_word_ratio: Any
    min_novel_words_for_ratio: Any
    shrink_min_tokens: Any
    shrink_ratio: Any
    growth_factor: Any
    growth_extra_tokens: Any
    # detail messages
    messages: Any

    @classmethod
    def from_dict(cls, data: dict) -> "ValidatorConfig":
        data = {k: v for k, v in data.items() if not k.startswith("_")}
        names = {f.name for f in fields(cls)}
        missing = sorted(names - data.keys())
        unknown = sorted(data.keys() - names)
        if missing or unknown:
            raise ValueError(
                f"Invalid validator config. Missing keys: {missing}. Unknown keys: {unknown}."
            )
        return cls(**data)

    def with_overrides(self, **changes) -> "ValidatorConfig":
        """Copy of this config with some values changed (handy in tests / tuning)."""
        return replace(self, **changes)


def load_config(path: Optional[str | os.PathLike] = None) -> ValidatorConfig:
    """Load config from `path`, else $CLEARVOICE_VALIDATOR_CONFIG, else the default JSON."""
    chosen = Path(path or os.environ.get(CONFIG_ENV_VAR) or DEFAULT_CONFIG_PATH)
    with open(chosen, encoding="utf-8") as fh:
        return ValidatorConfig.from_dict(json.load(fh))


# ---------------------------------------------------------------------------
# Small generic helpers (no domain knowledge)
# ---------------------------------------------------------------------------
def _alt(words) -> str:
    """Regex alternation of literal words, longest first."""
    return "|".join(re.escape(w) for w in sorted(set(words), key=len, reverse=True))


def _fill(pattern: str, **tokens: str) -> str:
    """Replace <TOKEN> placeholders in a config pattern."""
    for name, value in tokens.items():
        pattern = pattern.replace(f"<{name}>", value)
    return pattern


def _uniq(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------
class MeaningValidator:
    def __init__(self, config: Optional[ValidatorConfig] = None):
        c = self.cfg = config or load_config()

        # numbers
        self._units = {k.lower(): int(v) for k, v in c.number_units.items()}
        self._tens = {k.lower(): int(v) for k, v in c.number_tens.items()}
        self._scales = {k.lower(): int(v) for k, v in c.number_scales.items()}
        self._hundred = c.number_hundred_word.lower()
        self._connectors = {w.lower() for w in c.number_connectors}
        self._number_words = (
            set(self._units) | set(self._tens) | set(self._scales) | {self._hundred}
        )
        self._number_re = re.compile(c.number_pattern)
        self._word_re = re.compile(c.word_pattern)

        # dates
        months = [m.lower() for m in c.months]
        ambiguous = {m.lower() for m in c.ambiguous_months}
        date_tokens = {
            "MONTHS": _alt(months + [m.lower() for m in c.month_abbreviations]),
            "SUFFIXES": _alt(c.ordinal_suffixes),
        }
        self._month_day_re = re.compile(_fill(c.month_day_pattern, **date_tokens))
        self._day_month_re = re.compile(_fill(c.day_month_pattern, **date_tokens))
        self._numeric_date_re = re.compile(c.numeric_date_pattern)
        standalone = (
            [m for m in months if m not in ambiguous]
            + [w.lower() for w in c.weekdays]
            + [w.lower() for w in c.relative_days]
        )
        self._standalone_date_re = re.compile(
            _fill(c.standalone_date_pattern, WORDS=_alt(standalone))
        )
        self._date_words = set(standalone) | ambiguous

        # entities / pronouns
        self._sentence_split_re = re.compile(c.sentence_split_pattern)
        self._entity_strip_re = re.compile(c.entity_strip_pattern)
        self._entity_token_re = re.compile(c.entity_token_pattern)
        self._first_person_re = re.compile(c.first_person_pattern)
        self._pronouns = {p.lower() for p in c.pronouns}

        # negation
        neg_parts = [_fill(c.strong_negation_pattern, WORDS=_alt(c.negation_words))]
        if c.negation_contraction_suffixes:
            neg_parts.append(
                _fill(c.negation_contraction_pattern, SUFFIXES=_alt(c.negation_contraction_suffixes))
            )
        self._strong_neg_re = re.compile("|".join(neg_parts), re.I)
        self._weak_neg_re = re.compile(
            _fill(c.weak_negation_pattern, WORD=re.escape(c.weak_negation_word)), re.I
        )
        self._weak_neg_skip = {w.lower() for w in c.weak_negation_exclusions}

        # correction cues, invalid output, semantic risk
        self._cue_re = re.compile(
            _fill(c.correction_cue_pattern, WORDS=_alt(c.correction_cues)), re.I
        )
        self._invalid_re = re.compile(
            "|".join(f"(?:{p})" for p in c.invalid_output_patterns), re.I
        )
        self._function_words = {w.lower() for w in c.function_words}
        self._stem_re = re.compile(f"(?:{_alt(c.stem_suffixes)})$")

    def _msg(self, key: str, **kw) -> str:
        return self.cfg.messages[key].format(**kw)

    # ---- numbers ---------------------------------------------------------
    def _word_numbers(self, text: str) -> list[str]:
        """'five hundred and fifty' -> ['550']"""
        text = text.lower()
        for sep in self.cfg.number_word_separators:
            text = text.replace(sep, " ")
        words = self._word_re.findall(text)
        out: list[str] = []
        cur = total = 0
        active = False
        last: Optional[str] = None  # "unit" | "tens" | "scale"

        def flush() -> None:
            nonlocal cur, total, active, last
            if active:
                out.append(str(total + cur))
            cur = total = 0
            active = False
            last = None

        for i, w in enumerate(words):
            nxt = words[i + 1] if i + 1 < len(words) else None
            if w in self._units:
                if last == "unit":  # "five five" = stutter, not 10
                    flush()
                cur += self._units[w]
                active, last = True, "unit"
            elif w in self._tens:
                if last in ("unit", "tens"):
                    flush()
                cur += self._tens[w]
                active, last = True, "tens"
            elif w == self._hundred:
                if not active:
                    cur, active = 1, True
                cur *= int(self.cfg.number_hundred_value)
                last = "scale"
            elif w in self._scales:
                total += (cur or 1) * self._scales[w]
                cur = 0
                active, last = True, "scale"
            elif w in self._connectors and active and nxt in self._number_words:
                continue
            else:
                flush()
        flush()
        return out

    def extract_numbers(self, text: str) -> list[str]:
        """Digit numbers and number words, as normalized strings."""
        out: list[str] = []

        def grab(m: re.Match) -> str:
            f = float(m.group(0).replace(self.cfg.thousands_separator, ""))
            out.append(str(int(f)) if f.is_integer() else str(f))
            return " "

        out.extend(self._word_numbers(self._number_re.sub(grab, text)))
        return out

    # ---- dates -----------------------------------------------------------
    def extract_dates(self, text: str) -> tuple[list[str], str]:
        """(date tokens, text with those dates removed).

        So 'September 15th' is judged as a DATE, not as the number 15.
        """
        key = int(self.cfg.month_key_length)
        rest = text.lower()
        tokens: list[str] = []

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
        rest = self._numeric_date_re.sub(plain, rest)
        rest = self._standalone_date_re.sub(plain, rest)
        return tokens, rest

    # ---- entities & pronouns --------------------------------------------
    def extract_entities(self, text: str, known: Optional[list[str]] = None) -> list[str]:
        """Capitalized non-sentence-start words + profile known entities."""
        out: set[str] = set()
        for sentence in self._sentence_split_re.split(text):
            for i, raw in enumerate(sentence.split()):
                t = self._entity_strip_re.sub("", raw)
                if i == 0 or not t:
                    continue
                if self._first_person_re.match(t) or not self._entity_token_re.match(t):
                    continue
                if t.lower() in self._date_words:  # handled by the date check
                    continue
                out.add(t.lower())

        lower_text = text.lower()
        for k in known or []:
            kk = k.strip().lower()
            if kk and re.search(_fill(self.cfg.known_entity_pattern, ENTITY=re.escape(kk)), lower_text):
                out.add(kk)
        return sorted(out)

    def _pronouns_in(self, text: str) -> list[str]:
        return _uniq([w for w in self._word_re.findall(text.lower()) if w in self._pronouns])

    # ---- negation --------------------------------------------------------
    def _has_weak_negation(self, text: str) -> bool:
        """'no money' is a real negation; 'Friday, no Wednesday' is a correction."""
        for m in self._weak_neg_re.finditer(text):
            nxt = m.group(1).lower()
            if nxt in self._weak_neg_skip or nxt in self._date_words or nxt in self._number_words:
                continue
            return True
        return False

    def _negation_state(self, text: str) -> tuple[bool, bool]:
        return bool(self._strong_neg_re.search(text)), self._has_weak_negation(text)

    # ---- helpers ---------------------------------------------------------
    @staticmethod
    def _preserved(orig: list[str], rep: list[str], has_cue: bool) -> bool:
        """Rule for numbers / dates / entities:

        1. Nothing new may appear in repaired (no invention).
        2. If original had some, repaired must keep at least one (no silent wipe).
        3. Dropping a value is only OK if the speaker corrected themselves.
        """
        o, r = set(orig), set(rep)
        if not r <= o:
            return False
        if o and not r:
            return False
        if not has_cue and not o <= r:
            return False
        return True

    def _tokenize(self, text: str) -> list[str]:
        return self._word_re.findall(text.lower())

    def _stem(self, w: str) -> str:
        return self._stem_re.sub("", w) if len(w) >= int(self.cfg.stem_min_length) else w

    # ---- main ------------------------------------------------------------
    def _run_checks(
        self, original: str, repaired: str, known_entities: Optional[list[str]]
    ) -> tuple[str, Optional[str]]:
        c = self.cfg

        # 1. invalid output
        if not isinstance(original, str) or not isinstance(repaired, str):
            return R.INVALID_OUTPUT, self._msg("non_string")
        orig, rep = original.strip(), repaired.strip()
        if not rep:
            return R.INVALID_OUTPUT, self._msg("empty_output")
        if not orig:
            return R.INVALID_OUTPUT, self._msg("empty_original")
        if self._invalid_re.search(rep):
            return R.INVALID_OUTPUT, self._msg("llm_chatter")
        if rep == orig:
            return R.APPROVED, None

        has_cue = bool(self._cue_re.search(orig))

        # 2. dates (before numbers so "September 15 -> 16" is a DATE change)
        o_dates, o_rest = self.extract_dates(orig)
        r_dates, r_rest = self.extract_dates(rep)
        if not self._preserved(o_dates, r_dates, has_cue):
            return R.DATE_CHANGED, self._msg("changed", before=o_dates, after=r_dates)

        # 3. numbers (dates already removed)
        o_nums = _uniq(self.extract_numbers(o_rest))
        r_nums = _uniq(self.extract_numbers(r_rest))
        if not self._preserved(o_nums, r_nums, has_cue):
            return R.NUMBER_CHANGED, self._msg("changed", before=o_nums, after=r_nums)

        # 4. entities + pronouns
        o_ents = self.extract_entities(orig, known_entities)
        r_ents = self.extract_entities(rep, known_entities)
        if not self._preserved(o_ents, r_ents, has_cue):
            return R.ENTITY_CHANGED, self._msg("changed", before=o_ents, after=r_ents)
        o_pron = self._pronouns_in(orig)
        new_pron = [p for p in self._pronouns_in(rep) if p not in o_pron]
        if new_pron:
            return R.ENTITY_CHANGED, self._msg("new_pronouns", items=new_pron)

        # 5. negation
        o_neg, r_neg = self._negation_state(orig), self._negation_state(rep)
        if o_neg != r_neg:
            return R.NEGATION_CHANGED, self._msg("changed", before=o_neg, after=r_neg)

        
        o_tok, r_tok = self._tokenize(orig), self._tokenize(rep)
        o_stems = {self._stem(w) for w in o_tok}
        r_content = [w for w in r_tok if w not in self._function_words]
        novel = _uniq([self._stem(w) for w in r_content if self._stem(w) not in o_stems])
        ratio = len(novel) / max(len(r_content), 1)
        if len(novel) >= c.max_novel_words or (
            len(novel) >= c.min_novel_words_for_ratio and ratio > c.novel_word_ratio
        ):
            return R.SEMANTIC_RISK, self._msg("new_words", items=novel)
        if len(o_tok) >= c.shrink_min_tokens and len(r_tok) < len(o_tok) * c.shrink_ratio:
            return R.SEMANTIC_RISK, self._msg("too_short")
        if len(r_tok) > len(o_tok) * c.growth_factor + c.growth_extra_tokens:
            return R.SEMANTIC_RISK, self._msg("too_long")

        return R.APPROVED, None

    def validate(
        self, original: str, repaired: str, known_entities: Optional[list[str]] = None
    ) -> ValidationResult:
        """Returns exactly the frozen contract: {"approved": bool, "reason": str}."""
        reason, _ = self._run_checks(original, repaired, known_entities)
        return {"approved": reason == R.APPROVED, "reason": reason}

    def validate_with_detail(
        self, original: str, repaired: str, known_entities: Optional[list[str]] = None
    ) -> dict:
        """Same as validate() plus a `detail` string for logs/metrics."""
        reason, detail = self._run_checks(original, repaired, known_entities)
        return {"approved": reason == R.APPROVED, "reason": reason, "detail": detail}



@lru_cache(maxsize=1)
def get_default_validator() -> MeaningValidator:
    return MeaningValidator()


def validate(
    original: str, repaired: str, known_entities: Optional[list[str]] = None
) -> ValidationResult:
    return get_default_validator().validate(original, repaired, known_entities)


def validate_with_detail(
    original: str, repaired: str, known_entities: Optional[list[str]] = None
) -> dict:
    return get_default_validator().validate_with_detail(original, repaired, known_entities)