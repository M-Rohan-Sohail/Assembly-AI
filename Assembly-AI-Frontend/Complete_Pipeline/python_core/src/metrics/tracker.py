"""P3.5 Latency metrics: timestamp marks -> per-stage breakdown + total (TTFCA).

    metrics.mark(session_id, utterance_id, "audio_received")      # P1 calls this
    ...
    print(metrics.report(session_id, utterance_id).format())      # CP-13

Mark names, stages and the total are defined in metrics_config.json.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from src.common import load_json_config

DEFAULT_METRICS_CONFIG_PATH = Path(__file__).with_name("metrics_config.json")
METRICS_CONFIG_ENV_VAR = "CLEARVOICE_METRICS_CONFIG"


@dataclass(frozen=True)
class StageConfig:
    label: str
    start: str
    end: str


@dataclass(frozen=True)
class TotalConfig:
    label: str
    start: str
    end: list  # first mark in this list that exists is used


@dataclass(frozen=True)
class MetricsConfig:
    marks: list
    stages: list[StageConfig]
    total: TotalConfig
    decimals: int
    missing_text: str
    max_tracked_utterances: int


def load_metrics_config(path=None) -> MetricsConfig:
    return load_json_config(MetricsConfig, DEFAULT_METRICS_CONFIG_PATH, METRICS_CONFIG_ENV_VAR, path)


@dataclass(frozen=True)
class LatencyReport:
    session_id: str
    utterance_id: str
    marks: dict  # mark name -> ms
    stages: list  # [(label, ms or None)]
    total_label: str
    total_ms: Optional[float]
    decimals: int
    missing_text: str

    def _fmt(self, ms: Optional[float]) -> str:
        return self.missing_text if ms is None else f"{ms:.{self.decimals}f} ms"

    def format(self) -> str:
        width = max(len(label) for label, _ in [*self.stages, (self.total_label, None)])
        lines = [f"{label:<{width}}  {self._fmt(ms)}" for label, ms in self.stages]
        lines.append(f"{self.total_label:<{width}}  {self._fmt(self.total_ms)}")
        return "\n".join(lines)


class LatencyTracker:
    def __init__(self, config: Optional[MetricsConfig] = None, clock: Optional[Callable[[], float]] = None):
        self.config = config or load_metrics_config()
        self._clock = clock or (lambda: time.monotonic() * 1000.0)
        self._valid = set(self.config.marks)
        self._data: OrderedDict[tuple, dict] = OrderedDict()
        self._lock = threading.Lock()

    def now_ms(self) -> float:
        return self._clock()

    def mark(
        self, session_id: str, utterance_id: str, name: str,
        at_ms: Optional[float] = None, overwrite: bool = False,
    ) -> float:
        """Record a timestamp. By default the FIRST value wins (so P1 can set exact times early)."""
        if name not in self._valid:
            raise ValueError(f"Unknown mark '{name}'. Valid marks: {self.config.marks}")
        when = self._clock() if at_ms is None else at_ms
        key = (session_id, utterance_id)
        with self._lock:
            marks = self._data.setdefault(key, {})
            self._data.move_to_end(key)
            if overwrite or name not in marks:
                marks[name] = when
            while len(self._data) > self.config.max_tracked_utterances:  # bounded memory
                self._data.popitem(last=False)
            return marks[name]

    def report(self, session_id: str, utterance_id: str) -> LatencyReport:
        cfg = self.config
        with self._lock:
            marks = dict(self._data.get((session_id, utterance_id), {}))

        def span(start: str, end: str) -> Optional[float]:
            return marks[end] - marks[start] if start in marks and end in marks else None

        stages = [(s.label, span(s.start, s.end)) for s in cfg.stages]
        end_mark = next((m for m in cfg.total.end if m in marks), None)
        total = span(cfg.total.start, end_mark) if end_mark else None
        return LatencyReport(
            session_id, utterance_id, marks, stages, cfg.total.label, total, cfg.decimals, cfg.missing_text
        )

    def forget(self, session_id: str, utterance_id: str) -> None:
        with self._lock:
            self._data.pop((session_id, utterance_id), None)
