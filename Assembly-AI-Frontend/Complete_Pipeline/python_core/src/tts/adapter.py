"""TTSAdapter: text in -> AudioOutputEvent chunks out (sequenced, retried, cancellable)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from src.common import load_json_config

from .base import CancelToken, TTSError, TTSProvider
from .providers import create_provider

try:
    from src.contracts import AudioOutputEvent
except ImportError:  # pragma: no cover
    from contracts import AudioOutputEvent

log = logging.getLogger(__name__)

DEFAULT_TTS_CONFIG_PATH = Path(__file__).with_name("tts_config.json")
TTS_CONFIG_ENV_VAR = "CLEARVOICE_TTS_CONFIG"


@dataclass(frozen=True)
class EventTypesConfig:
    chunk: str
    final: str


@dataclass(frozen=True)
class TTSConfig:
    provider: str  # which entry of `providers` to use
    providers: dict  # provider name -> its own settings
    event_types: EventTypesConfig
    event_version: int
    audio_format: dict  # documentation for the player: encoding / sample_rate / channels
    chunk_size_bytes: int
    max_retries: int
    retry_backoff_s: float


def load_tts_config(path=None) -> TTSConfig:
    return load_json_config(TTSConfig, DEFAULT_TTS_CONFIG_PATH, TTS_CONFIG_ENV_VAR, path)


@dataclass(frozen=True)
class SynthesisResult:
    status: str  # one of TTSAdapter.COMPLETED / CANCELLED / SKIPPED
    chunks: int = 0


class TTSAdapter:
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"

    def __init__(self, provider: Optional[TTSProvider] = None, config: Optional[TTSConfig] = None):
        self.config = config or load_tts_config()
        self._provider = provider or create_provider(
            self.config.provider, self.config.providers[self.config.provider]
        )

    @property
    def audio_format(self) -> dict:
        return self.config.audio_format

    def synthesize(
        self,
        session_id: str,
        utterance_id: str,
        text: str,
        emit: Callable[[AudioOutputEvent], None],
        cancel: Optional[CancelToken] = None,
        on_first_chunk: Optional[Callable[[], None]] = None,
    ) -> SynthesisResult:
        """Stream `text` as audio events through `emit`. Raises TTSError if it cannot."""
        if not text or not text.strip():
            return SynthesisResult(self.SKIPPED)
        cancel = cancel or CancelToken()
        cfg = self.config
        sequence = 0

        def send(data: bytes, final: bool) -> None:
            nonlocal sequence
            if sequence == 0 and on_first_chunk:
                on_first_chunk()  # timestamp BEFORE handing audio to the player
            emit({
                "type": cfg.event_types.final if final else cfg.event_types.chunk,
                "version": cfg.event_version,
                "session_id": session_id,
                "utterance_id": utterance_id,
                "sequence": sequence,
                "audio_chunk": data,
                "is_final": final,
            })
            sequence += 1

        attempt = 0
        while True:
            buffer = bytearray()
            try:
                for block in self._provider.synthesize_stream(text, cancel):
                    if cancel.is_set():
                        return SynthesisResult(self.CANCELLED, sequence)
                    buffer.extend(block)
                    while len(buffer) >= cfg.chunk_size_bytes:
                        send(bytes(buffer[: cfg.chunk_size_bytes]), final=False)
                        del buffer[: cfg.chunk_size_bytes]
                if cancel.is_set():
                    return SynthesisResult(self.CANCELLED, sequence)
                if sequence == 0 and not buffer:
                    raise TTSError("TTS provider returned no audio")
                if buffer:
                    send(bytes(buffer), final=False)
                send(b"", final=True)
                return SynthesisResult(self.COMPLETED, sequence)
            except TTSError as exc:
                # Retrying is only safe if the listener has not heard anything yet.
                if sequence == 0 and attempt < cfg.max_retries:
                    attempt += 1
                    log.warning("TTS failed (%s); retry %d/%d", exc, attempt, cfg.max_retries)
                    time.sleep(cfg.retry_backoff_s * attempt)
                    continue
                raise
