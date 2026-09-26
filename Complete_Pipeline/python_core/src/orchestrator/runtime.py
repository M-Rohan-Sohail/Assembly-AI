"""Person3Runtime: everything Person 3 needs, ready to drop into Person 1's main.py.

    person3 = Person3Runtime()          # once, at startup
    person3.submit(transcript_event)    # for every FINAL transcript
    person3.close()                     # at shutdown (waits for speech to finish)
"""

from __future__ import annotations

import logging
from concurrent.futures import Future, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from src.common import load_json_config
from src.metrics import LatencyTracker
from src.tts import load_tts_config

from .factory import build_orchestrator
from .orchestrator import SessionOrchestrator, UtteranceResult
from .repair_clients import RepairProvider
from .sinks import audio_format_from, create_sink

try:
    from src.contracts import AudioOutputEvent, TranscriptEvent
except ImportError:  # pragma: no cover
    from contracts import AudioOutputEvent, TranscriptEvent

log = logging.getLogger(__name__)

DEFAULT_RUNTIME_CONFIG_PATH = Path(__file__).with_name("runtime_config.json")
RUNTIME_CONFIG_ENV_VAR = "CLEARVOICE_RUNTIME_CONFIG"


@dataclass(frozen=True)
class RuntimeConfig:
    sinks: list
    wav_output_dir: str
    wav_name_pattern: str
    playback_mark: str
    print_result: bool
    print_latency: bool
    shutdown_wait_s: float


def load_runtime_config(path=None) -> RuntimeConfig:
    return load_json_config(RuntimeConfig, DEFAULT_RUNTIME_CONFIG_PATH, RUNTIME_CONFIG_ENV_VAR, path)


class Person3Runtime:
    def __init__(
        self,
        config: Optional[RuntimeConfig] = None,
        sink: Optional[Callable[[AudioOutputEvent], None]] = None,
        repair: Optional[RepairProvider] = None,
    ):
        self.config = config or load_runtime_config()
        self.metrics = LatencyTracker()
        self._sink = sink or create_sink(
            self.config.sinks,
            audio_format_from(load_tts_config().audio_format),
            self.config.wav_output_dir,
            self.config.wav_name_pattern,
        )
        self.orchestrator: SessionOrchestrator = build_orchestrator(
            emit=self._play, on_error=self._on_error, metrics=self.metrics, repair=repair
        )
        self._pending: set[Future] = set()

    @property
    def is_speaking(self) -> bool:
        """True while any utterance is still being processed / spoken (use to mute the mic)."""
        return bool(self._pending)

    def submit(self, event: TranscriptEvent) -> Optional[Future]:
        """Never raises: this is called from the STT callback thread."""
        try:
            future = self.orchestrator.submit(event)
        except Exception as exc:  # e.g. the event is missing session_id / utterance_id
            self._on_error("submit", "?", "?", exc)
            return None
        self._pending.add(future)
        future.add_done_callback(self._finished)
        return future

    def close(self) -> None:
        wait(list(self._pending), timeout=self.config.shutdown_wait_s)
        self.orchestrator.shutdown()
        getattr(self._sink, "close", lambda: None)()

    # ---- internals --------------------------------------------------------
    def _play(self, event: AudioOutputEvent) -> None:
        if event["sequence"] == 0:  # first audio reaches the listener now
            self.metrics.mark(event["session_id"], event["utterance_id"], self.config.playback_mark)
        self._sink(event)

    def _finished(self, future: Future) -> None:
        self._pending.discard(future)
        exc = future.exception()
        if exc is not None:
            log.error("utterance processing crashed: %s", exc)
            return
        result: UtteranceResult = future.result()
        if self.config.print_result and result.spoken_text:
            print(f"\n[SPOKEN:{result.source}] {result.spoken_text}")
        if self.config.print_latency and result.report:
            print(result.report.format())

    @staticmethod
    def _on_error(stage: str, session_id: str, utterance_id: str, exc: Exception) -> None:
        print(f"\n[PERSON3 {stage.upper()} ERROR] {exc}")
