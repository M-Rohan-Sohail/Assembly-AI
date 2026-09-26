"""ClearVoice meaning validation (Person 3).

    from src.validation import MeaningValidator
    validator = MeaningValidator()
    result = validator.validate(original_text, repaired_text)   # {"approved", "reason"}

Layout:
    config.py       typed config sections + loader        (validator_config.json)
    extractors.py   reusable finders: numbers, dates, entities, negation, ...
    analysis.py     cached per-text analysis shared by the checks
    checks.py       one small class per check (+ registry to add your own)
    guard.py        rejects broken input before checking
    validator.py    MeaningValidator: runs the configured checks in order
    verdict.py      result object
"""

from .checks import Check, available_checks, register_check
from .config import ValidatorConfig, load_config
from .extractors import Toolkit
from .validator import MeaningValidator, validate, validate_with_detail
from .verdict import Verdict

__all__ = [
    "Check", "MeaningValidator", "Toolkit", "ValidatorConfig", "Verdict",
    "available_checks", "load_config", "register_check", "validate", "validate_with_detail",
]
