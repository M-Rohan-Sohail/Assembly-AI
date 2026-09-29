"""The one place that imports the shared team contracts.

Works whether the project is run from the repo root (src.contracts) or from src/.
"""

try:
    from src.contracts import ValidationReason, ValidationResult
except ImportError:  # pragma: no cover
    from contracts import ValidationReason, ValidationResult

__all__ = ["ValidationReason", "ValidationResult"]
