"""TTS building blocks shared by every provider."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Iterator


class TTSError(Exception):
    """The TTS provider failed (network, bad status, no audio, ...)."""


class CancelToken:
    """Thread-safe 'stop speaking' flag (barge-in, session closed, ...)."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def set(self) -> None:
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()


class TTSProvider(ABC):
    """A provider turns text into a stream of audio byte blocks."""

    @abstractmethod
    def synthesize_stream(self, text: str, cancel: CancelToken) -> Iterator[bytes]:
        """Yield audio blocks (any size). Raise TTSError on failure. Stop if cancel is set."""
