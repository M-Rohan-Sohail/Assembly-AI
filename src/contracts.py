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
