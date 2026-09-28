"""P3.4 Session orchestration: TranscriptEvent -> repair -> validate/fallback -> TTS."""

from .factory import build_orchestrator
from .orchestrator import SessionOrchestrator, Stage, Status, UtteranceResult
from .repair_clients import (
    HttpRepairClient, MockRepairClient, RepairError, RepairProvider, create_repair_client,
)

__all__ = [
    "HttpRepairClient", "MockRepairClient", "RepairError", "RepairProvider", "SessionOrchestrator",
    "Stage", "Status", "UtteranceResult", "build_orchestrator", "create_repair_client",
]
