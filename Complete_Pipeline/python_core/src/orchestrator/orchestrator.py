"""P3.4 Session Orchestrator - connects Person 1 -> Person 2 -> Person 3.

    TranscriptEvent (P1) -> repair (P2) -> validator + fallback -> TTS -> AudioOutputEvent

Every provider failure is contained: a repair timeout/crash, a validator bug or a
TTS outage never stops the session. The listener hears the safest text available.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from src.common import load_json_config
from src.metrics import LatencyReport, LatencyTracker
from src.tts import CancelToken, TTSAdapter, TTSError
from src.validation.fallback import FallbackEngine

from .repair_clients import RepairProvider

try:
    from src.contracts import AudioOutputEvent, TranscriptEvent
except ImportError:  # pragma: no cover
    from contracts import AudioOutputEvent, TranscriptEvent

log = logging.getLogger(__name__)

DEFAULT_ORCHESTRATOR_CONFIG_PATH = Path(__file__).with_name("orchestrator_config.json")
ORCHESTRATOR_CONFIG_ENV_VAR = "CLEARVOICE_ORCHESTRATOR_CONFIG"


@dataclass(frozen=True)
class MarksConfig:
    on_receive: list
    llm_start: str
    llm_end: str
    validation: str
    tts_first_chunk: str


@dataclass(frozen=True)
class OrchestratorConfig:
    process_event_types: list
    repair_timeout_s: float
    repair_workers: int
    marks: MarksConfig


def load_orchestrator_config(path=None) -> OrchestratorConfig:
    return load_json_config(
        OrchestratorConfig, DEFAULT_ORCHESTRATOR_CONFIG_PATH, ORCHESTRATOR_CONFIG_ENV_VAR, path
    )


class Stage:
    """Names passed to on_error so you know which step failed."""
    REPAIR = "repair"
    FALLBACK = "fallback"
    TTS = "tts"
    PLAYBACK = "playback"  # the sink / speaker that receives the audio


class Status:
    SPOKEN = "spoken"
    IGNORED = "ignored"  # not a final transcript / empty text
    CANCELLED = "cancelled"
    TTS_FAILED = "tts_failed"
    PLAYBACK_FAILED = "playback_failed"


@dataclass
class UtteranceResult:
    session_id: str
    utterance_id: str
    status: str
    spoken_text: str = ""
    source: str = ""  # which fallback level was spoken: repaired / safer / original
    attempts: list = field(default_factory=list)
    report: Optional[LatencyReport] = None


class _Session:
    def __init__(self, session_id: str):
        self.id = session_id
        self.cancel = CancelToken()
        self.lock = threading.Lock()  # one utterance at a time, in order
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"cv-{session_id}")


class SessionOrchestrator:
    def __init__(
        self,
        repair: RepairProvider,
        fallback: FallbackEngine,
        tts: TTSAdapter,
        metrics: LatencyTracker,
        emit: Callable[[AudioOutputEvent], None],
        config: Optional[OrchestratorConfig] = None,
        on_error: Optional[Callable[[str, str, str, Exception], None]] = None,
        known_entities_for: Optional[Callable[[str], list]] = None,
    ):
        """
        emit              receives every AudioOutputEvent (send it to the player / listener)
        on_error          on_error(stage, session_id, utterance_id, exception) - for logging/alerts
        known_entities_for  session_id -> list of protected names (Person 2's UserProfile)
        """
        self.config = config or load_orchestrator_config()
        self._repair = repair
        self._fallback = fallback
        self._tts = tts
        self.metrics = metrics
        self._emit = emit
        self._on_error = on_error
        self._known_entities_for = known_entities_for
        self._repair_pool = ThreadPoolExecutor(max_workers=self.config.repair_workers, thread_name_prefix="cv-repair")
        self._sessions: dict[str, _Session] = {}
        self._sessions_lock = threading.Lock()

    # ---- session lifecycle ----------------------------------------------
    def open_session(self, session_id: str) -> None:
        self._session(session_id)

    def close_session(self, session_id: str) -> None:
        with self._sessions_lock:
            session = self._sessions.pop(session_id, None)
        if session:
            session.cancel.set()
            session.executor.shutdown(wait=False, cancel_futures=True)

    def cancel_speech(self, session_id: str) -> None:
        """Barge-in: stop whatever is being spoken now; the session stays open."""
        session = self._session(session_id)
        session.cancel.set()
        session.cancel = CancelToken()

    def shutdown(self) -> None:
        for sid in list(self._sessions):
            self.close_session(sid)
        self._repair_pool.shutdown(wait=False, cancel_futures=True)

    def _session(self, session_id: str) -> _Session:
        with self._sessions_lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = _Session(session_id)
            return self._sessions[session_id]

    # ---- entry points -----------------------------------------------------
    def submit(self, event: TranscriptEvent) -> Future:
        """Non-blocking (use from Person 1's STT callback). Order is kept per session."""
        session = self._session(event["session_id"])
        return session.executor.submit(self.process_utterance, event)

    def process_utterance(self, event: TranscriptEvent) -> UtteranceResult:
        """Blocking: run one transcript through the whole pipeline."""
        sid, uid = event["session_id"], event["utterance_id"]
        text = (event.get("text") or "").strip()
        if event.get("type") not in self.config.process_event_types or not text:
            return UtteranceResult(sid, uid, Status.IGNORED)

        session = self._session(sid)
        with session.lock:
            cancel = session.cancel
            marks = self.config.marks
            for name in marks.on_receive:  # first value wins, so Person 1's exact times are kept
                self.metrics.mark(sid, uid, name)

            repaired = self._run_repair(event, sid, uid)
            decision = self._run_fallback(text, repaired, sid, uid)
            result = UtteranceResult(sid, uid, Status.SPOKEN, decision.text, decision.source, decision.attempts)

            emit, playback_failed = self._guarded_emit(sid, uid)
            try:
                outcome = self._tts.synthesize(
                    sid, uid, decision.text, emit, cancel,
                    on_first_chunk=lambda: self.metrics.mark(sid, uid, marks.tts_first_chunk),
                )
                if outcome.status == TTSAdapter.CANCELLED:
                    result.status = Status.CANCELLED
            except TTSError as exc:
                self._report_error(Stage.TTS, sid, uid, exc)
                result.status = Status.TTS_FAILED
            if playback_failed():
                result.status = Status.PLAYBACK_FAILED

            result.report = self.metrics.report(sid, uid)
            return result

    # ---- pipeline steps ---------------------------------------------------
    def _run_repair(self, event: TranscriptEvent, sid: str, uid: str) -> Optional[str]:
        marks = self.config.marks
        self.metrics.mark(sid, uid, marks.llm_start)
        try:
            future = self._repair_pool.submit(self._repair.repair, event)
            try:
                result = future.result(timeout=self.config.repair_timeout_s)
            except FutureTimeout:
                future.cancel()
                raise TimeoutError(f"repair took longer than {self.config.repair_timeout_s}s")
            return result.get("repaired_text")
        except Exception as exc:  # any repair failure -> fall back to safer text
            self._report_error(Stage.REPAIR, sid, uid, exc)
            return None
        finally:
            self.metrics.mark(sid, uid, marks.llm_end)

    def _run_fallback(self, original: str, repaired: Optional[str], sid: str, uid: str):
        marks = self.config.marks
        try:
            known = self._known_entities_for(sid) if self._known_entities_for else None
            decision = self._fallback.resolve(original, repaired, known)
        except Exception as exc:  # a validator bug must never block speech
            self._report_error(Stage.FALLBACK, sid, uid, exc)
            decision = _OriginalOnly(original)
        finally:
            self.metrics.mark(sid, uid, marks.validation)
        return decision

    def _guarded_emit(self, sid: str, uid: str):
        """Wrap emit so a broken player is reported once and never crashes the pipeline."""
        state = {"failed": False}

        def emit(event: AudioOutputEvent) -> None:
            if state["failed"]:
                return  # player is broken for this utterance: drop the rest
            try:
                self._emit(event)
            except Exception as exc:
                state["failed"] = True
                self._report_error(Stage.PLAYBACK, sid, uid, exc)

        return emit, lambda: state["failed"]

    def _report_error(self, stage: str, sid: str, uid: str, exc: Exception) -> None:
        log.warning("%s failed for %s/%s: %s", stage, sid, uid, exc)
        if self._on_error:
            try:
                self._on_error(stage, sid, uid, exc)
            except Exception:  # the error handler itself must not break the pipeline
                log.exception("on_error handler raised")


@dataclass
class _OriginalOnly:
    """Last-resort decision if the fallback engine itself crashed."""
    text: str
    source: str = "original"
    attempts: list = field(default_factory=list)
