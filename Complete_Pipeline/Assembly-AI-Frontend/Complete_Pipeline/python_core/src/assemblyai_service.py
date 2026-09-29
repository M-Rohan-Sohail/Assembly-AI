import assemblyai as aai
from assemblyai.streaming.v3 import RealTimeTranscriber
from assemblyai.streaming.v3 import BeginEvent, TurnEvent, TerminationEvent, RealTimeError
from typing import Callable, Optional, Any
from contracts import TranscriptEvent
from assemblyai.streaming.v3.models import RealTimeEvents

class AssemblyAIService:
    def __init__(self, api_key: str):
        aai.settings.api_key = api_key
        
        self.transcriber: Optional[RealTimeTranscriber] = None
        self.on_transcript_event: Optional[Callable[[TranscriptEvent], None]] = None
        
        self.current_session_id = None
        self.last_transcript = ""
        self.last_confidence: Optional[float] = None
        self.last_start_ms = 0
        self.last_end_ms = 0
        
    def _on_data(self, transcriber: RealTimeTranscriber, turn_event: Any):
        transcript_text = getattr(turn_event, 'transcript', '').strip()
        is_final = getattr(turn_event, 'end_of_turn', False)
        
        words = getattr(turn_event, 'words', [])
        if words:
            self.last_start_ms = getattr(words[0], 'start', self.last_start_ms)
            self.last_end_ms = getattr(words[-1], 'end', self.last_end_ms)
            
        confidence = getattr(turn_event, 'end_of_turn_confidence', None)
        if confidence is not None:
            self.last_confidence = confidence

        if transcript_text:
            self.last_transcript = transcript_text

        # If it is final but this specific event has empty transcript (e.g. after force_endpoint),
        # use the last seen transcript for this turn.
        text_to_emit = transcript_text if transcript_text else (self.last_transcript if is_final else '')
        
        if not text_to_emit:
            return
            
        event_type = "transcript.final" if is_final else "transcript.partial"

        event: TranscriptEvent = {
            "type": event_type,
            "version": 1,
            "session_id": self.current_session_id or "unknown",
            "utterance_id": str(getattr(turn_event, 'turn_order', 'unknown')),
            "text": text_to_emit,
            "is_final": is_final,
            "confidence": self.last_confidence,
            "start_ms": self.last_start_ms,
            "end_ms": self.last_end_ms
        }
        
        if is_final:
            self.last_transcript = ""
            self.last_confidence = None
            self.last_start_ms = 0
            self.last_end_ms = 0
            
        if self.on_transcript_event:
            self.on_transcript_event(event)

    def _on_error(self, transcriber: RealTimeTranscriber, error: RealTimeError):
        print(f"\nAssemblyAI Error: {error}")

    def _on_open(self, transcriber: RealTimeTranscriber, session_opened: BeginEvent):
        print("AssemblyAI Real-Time connection opened")

    def _on_close(self, transcriber: RealTimeTranscriber, session_closed: TerminationEvent):
        print("AssemblyAI Real-Time connection closed")

    def start_session(self, session_id: str, sample_rate: int = 16000):
        """Connects to the AssemblyAI Real-Time streaming API."""
        self.current_session_id = session_id
        self.last_transcript = ""
        self.last_confidence = None
        self.last_start_ms = 0
        self.last_end_ms = 0
        
        from assemblyai.streaming.v3 import RealTimeTranscriberOptions, RealTimeParameters
        options = RealTimeTranscriberOptions(
            api_key=aai.settings.api_key,
        )
        
        self.transcriber = RealTimeTranscriber(options=options)
        self.transcriber.on(RealTimeEvents.Turn, self._on_data)
        self.transcriber.on(RealTimeEvents.Error, self._on_error)
        self.transcriber.on(RealTimeEvents.Begin, self._on_open)
        self.transcriber.on(RealTimeEvents.Termination, self._on_close)
        
        params = RealTimeParameters(
            sample_rate=sample_rate,
            language_codes=["en"]
        )
        self.transcriber.connect(params)
        
    def send_audio(self, payload: bytes):
        """Streams raw audio bytes (int16) to AssemblyAI."""
        if self.transcriber:
            self.transcriber.stream(payload)
            
    def force_endpoint(self):
        """Forces the current turn to end immediately."""
        if self.transcriber:
            self.transcriber.force_endpoint()

    def flush_final(self):
        """If there is any pending unfinalized transcript, emit it as final."""
        if self.last_transcript and self.on_transcript_event:
            event: TranscriptEvent = {
                "type": "transcript.final",
                "version": 1,
                "session_id": self.current_session_id or "unknown",
                "utterance_id": "flushed_final",
                "text": self.last_transcript,
                "is_final": True,
                "confidence": self.last_confidence,
                "start_ms": self.last_start_ms,
                "end_ms": self.last_end_ms
            }
            self.last_transcript = ""
            self.last_confidence = None
            self.last_start_ms = 0
            self.last_end_ms = 0
            self.on_transcript_event(event)

    def end_session(self):
        """Closes the connection to AssemblyAI."""
        if self.transcriber:
            self.flush_final()
            self.transcriber.disconnect(terminate=True)
            self.transcriber = None
