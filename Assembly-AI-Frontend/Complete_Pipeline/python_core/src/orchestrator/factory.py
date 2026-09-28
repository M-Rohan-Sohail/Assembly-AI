"""One call that wires everything from the JSON configs - use this in main.py."""

from __future__ import annotations

from typing import Callable, Optional

from src.metrics import LatencyTracker
from src.tts import TTSAdapter
from src.validation import MeaningValidator
from src.validation.fallback import FallbackEngine

from .orchestrator import SessionOrchestrator
from .repair_clients import RepairProvider, create_repair_client

try:
    from src.contracts import AudioOutputEvent
except ImportError:  # pragma: no cover
    from contracts import AudioOutputEvent


def build_orchestrator(
    emit: Callable[[AudioOutputEvent], None],
    on_error: Optional[Callable] = None,
    known_entities_for: Optional[Callable[[str], list]] = None,
    repair: Optional[RepairProvider] = None,
    mock_overrides: Optional[dict] = None,
    metrics: Optional[LatencyTracker] = None,
) -> SessionOrchestrator:
    """Default wiring. Pass `repair=` to plug in Person 2's real client directly."""
    validator = MeaningValidator()
    fallback = FallbackEngine(validator)
    repair = repair or create_repair_client(rewriter=fallback.rewriter, mock_overrides=mock_overrides)
    return SessionOrchestrator(
        repair=repair,
        fallback=fallback,
        tts=TTSAdapter(),
        metrics=metrics or LatencyTracker(),
        emit=emit,
        on_error=on_error,
        known_entities_for=known_entities_for,
    )
