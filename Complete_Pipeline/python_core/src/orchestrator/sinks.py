"""Where the spoken audio goes. A sink is any callable taking an AudioOutputEvent.

  - speaker : plays through the sound card (needs `pip install pyaudio`, already used by Person 1)
  - wav     : saves each utterance as a .wav file (works on a machine with no speakers)

Which ones run is chosen in runtime_config.json. Audio format comes from tts_config.json.
"""

from __future__ import annotations

import logging
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from src.common import ConfigError, build

try:
    from src.contracts import AudioOutputEvent
except ImportError:  # pragma: no cover
    from contracts import AudioOutputEvent

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AudioFormat:
    encoding: str
    sample_rate: int
    channels: int
    sample_width_bytes: int


def audio_format_from(tts_audio_format: dict) -> AudioFormat:
    return build(AudioFormat, tts_audio_format, "tts.audio_format")


class WavFileSink:
    """Collects the chunks of each utterance and writes one .wav when the final chunk arrives."""

    def __init__(self, directory: str | Path, name_pattern: str, fmt: AudioFormat):
        self._dir, self._pattern, self._fmt = Path(directory), name_pattern, fmt
        self._buffers: dict[tuple, bytearray] = {}
        self.last_path: Optional[Path] = None

    def __call__(self, event: AudioOutputEvent) -> None:
        key = (event["session_id"], event["utterance_id"])
        self._buffers.setdefault(key, bytearray()).extend(event["audio_chunk"])
        if event["is_final"]:
            self._write(key, bytes(self._buffers.pop(key)))

    def _write(self, key: tuple, audio: bytes) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / self._pattern.format(session_id=key[0], utterance_id=key[1])
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(self._fmt.channels)
            wf.setsampwidth(self._fmt.sample_width_bytes)
            wf.setframerate(self._fmt.sample_rate)
            wf.writeframes(audio)
        self.last_path = path
        log.info("saved spoken audio to %s", path)

    def close(self) -> None:
        self._buffers.clear()  # unfinished (cancelled) utterances are discarded


class SpeakerSink:
    """Plays chunks through PyAudio. The device is opened on first use."""

    def __init__(self, fmt: AudioFormat, pyaudio_module=None):
        self._fmt, self._module = fmt, pyaudio_module
        self._pa = self._stream = None

    def _open(self) -> None:
        module = self._module or __import__("pyaudio")
        self._pa = module.PyAudio()
        self._stream = self._pa.open(
            format=self._pa.get_format_from_width(self._fmt.sample_width_bytes),
            channels=self._fmt.channels,
            rate=self._fmt.sample_rate,
            output=True,
        )

    def __call__(self, event: AudioOutputEvent) -> None:
        if not event["audio_chunk"]:
            return
        if self._stream is None:
            self._open()
        self._stream.write(event["audio_chunk"])  # blocks while playing = natural pacing

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop_stream()
            self._stream.close()
            self._pa.terminate()
            self._stream = self._pa = None


class MultiSink:
    """Send every event to all sinks; one failing sink does not starve the others."""

    def __init__(self, sinks: list[Callable]):
        self._sinks = sinks

    def __call__(self, event: AudioOutputEvent) -> None:
        errors = []
        for sink in self._sinks:
            try:
                sink(event)
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise errors[0]

    def close(self) -> None:
        for sink in self._sinks:
            getattr(sink, "close", lambda: None)()


def create_sink(names: list[str], fmt: AudioFormat, wav_dir: str, wav_pattern: str, pyaudio_module=None):
    factories = {
        "speaker": lambda: SpeakerSink(fmt, pyaudio_module),
        "wav": lambda: WavFileSink(wav_dir, wav_pattern, fmt),
    }
    unknown = [n for n in names if n not in factories]
    if unknown:
        raise ConfigError(f"Unknown sink(s) {unknown}. Available: {sorted(factories)}")
    sinks = [factories[n]() for n in names]
    return sinks[0] if len(sinks) == 1 else MultiSink(sinks)
