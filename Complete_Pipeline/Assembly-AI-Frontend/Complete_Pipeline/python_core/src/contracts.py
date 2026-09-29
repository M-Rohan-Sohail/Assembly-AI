from typing import TypedDict, Optional

class AudioChunk(TypedDict):
    session_id: str
    sequence: int
    timestamp_ms: int
    payload: bytes
    sample_rate: int
    channels: int

class VadEvent(TypedDict):
    session_id: str
    state: str  # "speech" | "silence"
    timestamp_ms: int
    silence_duration_ms: Optional[int]

class EndpointDecision(TypedDict):
    session_id: str
    utterance_id: str
    finalized: bool
    reason: str  # "pause" | "transcript_final" | "manual" | "timeout"
    timestamp_ms: int

class TranscriptEvent(TypedDict):
    type: str  # "transcript.partial" | "transcript.final"
    version: int
    session_id: str
    utterance_id: str
    text: str
    is_final: bool
    confidence: Optional[float]
    start_ms: int
    end_ms: int
    
# ---- Person 3 / shared contracts ----
# Paste these at the BOTTOM of src/contracts.py (don't replace the whole file).

class ValidationReason:
    """Single source of truth for validator reason names."""
    APPROVED = "approved"
    NUMBER_CHANGED = "number_changed"
    DATE_CHANGED = "date_changed"
    ENTITY_CHANGED = "entity_changed"
    NEGATION_CHANGED = "negation_changed"
    SEMANTIC_RISK = "semantic_risk"
    INVALID_OUTPUT = "invalid_output"


class ValidationResult(TypedDict):
    approved: bool
    reason: str  # one of the ValidationReason values


class AudioOutputEvent(TypedDict):
    type: str  # "audio.chunk" | "audio.final"
    version: int
    session_id: str
    utterance_id: str
    sequence: int
    audio_chunk: bytes
    is_final: bool


# Person 2 owns this one - it is the shape Person 3 expects. If P2 already added
# RepairResult to contracts.py, skip these two.
class RepairChange(TypedDict, total=False):
    type: str
    original: str
    replacement: str


class RepairResult(TypedDict):
    type: str  # "repair.completed"
    version: int
    session_id: str
    utterance_id: str
    original_text: str
    repaired_text: str
    confidence: float
    changes: list
