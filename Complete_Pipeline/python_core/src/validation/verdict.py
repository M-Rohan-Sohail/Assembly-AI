"""The outcome of a validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ._contracts import ValidationReason, ValidationResult


@dataclass(frozen=True)
class Verdict:
    reason: str
    detail: Optional[str] = None  # human-readable note for logs / metrics

    @property
    def approved(self) -> bool:
        return self.reason == ValidationReason.APPROVED

    @classmethod
    def approve(cls) -> "Verdict":
        return cls(ValidationReason.APPROVED)

    @classmethod
    def reject(cls, reason: str, detail: Optional[str] = None) -> "Verdict":
        return cls(reason, detail)

    def to_result(self) -> ValidationResult:
        """Exactly the frozen team contract."""
        return {"approved": self.approved, "reason": self.reason}

    def to_dict(self) -> dict:
        """Contract + detail (for logging)."""
        return {**self.to_result(), "detail": self.detail}
