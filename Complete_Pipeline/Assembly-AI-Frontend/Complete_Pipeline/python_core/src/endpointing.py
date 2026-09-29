import torch
import numpy as np
import time
from typing import Optional, Tuple
try:
    from src.contracts import AudioChunk, VadEvent, EndpointDecision
except ImportError:
    from contracts import AudioChunk, VadEvent, EndpointDecision

class EndpointingEngine:
    def __init__(self, sample_rate: int = 16000, min_silence_duration_ms: int = 1500):
        self.sample_rate = sample_rate
        self.min_silence_duration_ms = min_silence_duration_ms
        
        print("Loading Silero VAD model...")
        self.model, utils = torch.hub.load(
            repo_or_dir='snakers4/silero-vad',
            model='silero_vad',
            force_reload=False,
            onnx=False,
            trust_repo=True
        )
        self.get_speech_timestamps, _, _, self.VADIterator, _ = utils
        # VADIterator maintains state across chunks
        self.vad_iterator = self.VADIterator(self.model)
        
        self.is_speaking = False
        self.silence_start_time_ms: Optional[int] = None
        self.sample_buffer = np.empty(0, dtype=np.int16)
        
    def reset(self):
        self.vad_iterator.reset_states()
        self.is_speaking = False
        self.silence_start_time_ms = None
        self.sample_buffer = np.empty(0, dtype=np.int16)

    def process_chunk(self, chunk: AudioChunk) -> Tuple[Optional[VadEvent], Optional[EndpointDecision]]:
        # Convert incoming bytes (int16) and append to internal buffer
        new_samples = np.frombuffer(chunk['payload'], dtype=np.int16)
        if len(self.sample_buffer) > 0:
            self.sample_buffer = np.concatenate([self.sample_buffer, new_samples])
        else:
            self.sample_buffer = new_samples

        vad_event: Optional[VadEvent] = None
        endpoint_decision: Optional[EndpointDecision] = None
        timestamp_ms = chunk['timestamp_ms']

        # Slice into exact 512-sample blocks required by Silero VAD
        while len(self.sample_buffer) >= 512:
            frame = self.sample_buffer[:512]
            self.sample_buffer = self.sample_buffer[512:]
            
            tensor = torch.from_numpy(frame.copy()).float() / 32768.0
            vad_output = self.vad_iterator(tensor, return_seconds=True)
            
            if vad_output is not None:
                if 'start' in vad_output:
                    self.is_speaking = True
                    self.silence_start_time_ms = None
                    vad_event = {
                        "session_id": chunk['session_id'],
                        "state": "speech",
                        "timestamp_ms": timestamp_ms,
                        "silence_duration_ms": None
                    }
                elif 'end' in vad_output:
                    self.is_speaking = False
                    self.silence_start_time_ms = timestamp_ms
                    vad_event = {
                        "session_id": chunk['session_id'],
                        "state": "silence",
                        "timestamp_ms": timestamp_ms,
                        "silence_duration_ms": 0
                    }
                    
        # Handle custom endpointing (CP-3: ignore short pauses)
        if not self.is_speaking and self.silence_start_time_ms is not None:
            silence_duration = timestamp_ms - self.silence_start_time_ms
            
            # Output silence event
            if vad_event is None:
                vad_event = {
                    "session_id": chunk['session_id'],
                    "state": "silence",
                    "timestamp_ms": timestamp_ms,
                    "silence_duration_ms": silence_duration
                }
            
            # Check if silence exceeded the threshold
            if silence_duration >= self.min_silence_duration_ms:
                endpoint_decision = {
                    "session_id": chunk['session_id'],
                    "utterance_id": f"{chunk['session_id']}_{timestamp_ms}",
                    "finalized": True,
                    "reason": "pause",
                    "timestamp_ms": timestamp_ms
                }
                # Reset silence tracker to prevent continuous endpoint events
                self.silence_start_time_ms = None
                
        return vad_event, endpoint_decision
