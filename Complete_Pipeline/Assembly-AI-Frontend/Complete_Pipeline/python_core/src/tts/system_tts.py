"""SystemTTSProvider: offline speech via the operating system's own voices
(no API key, no network, no cost). Register it with @register_provider("system")
so it is picked purely by setting "provider": "system" in tts_config.json,
exactly like the "mock" and "http" providers.

Uses pyttsx3, which drives SAPI5 on Windows, NSSpeechSynthesizer on macOS and
espeak on Linux. pyttsx3 cannot hand us a live stream, so we synthesize to a
temporary WAV and then stream that file out in blocks: latency is "whole
utterance" rather than true first-chunk streaming.

Emits raw PCM: signed 16-bit little-endian, mono, at `sample_rate`. Make sure
tts_config.json's top-level "audio_format" says the same sample_rate.
"""

from __future__ import annotations

import logging
import struct
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from src.common import build

from .base import CancelToken, TTSError, TTSProvider
from .providers import register_provider

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SystemTTSConfig:
    sample_rate: int
    block_size_bytes: int
    voice: str  # "" = OS default voice; substring match against voice name/id
    rate: int  # words per minute, 0 = engine default
    volume: float  # 0.0 - 1.0


@register_provider("system")
class SystemTTSProvider(TTSProvider):
    def __init__(self, cfg: SystemTTSConfig):
        self.cfg = cfg

    @classmethod
    def from_dict(cls, data: dict) -> "SystemTTSProvider":
        return cls(build(SystemTTSConfig, data, "tts.providers.system"))

    # -- public API ---------------------------------------------------------
    def synthesize_stream(self, text: str, cancel: CancelToken) -> Iterator[bytes]:
        if cancel.is_set():
            return
        wav_bytes = self._synthesize_to_wav(text)
        if cancel.is_set():
            return
        pcm = self._wav_to_pcm16_mono(wav_bytes, self.cfg.sample_rate)
        if not pcm:
            raise TTSError("system TTS produced no audio")
        block = self.cfg.block_size_bytes
        for start in range(0, len(pcm), block):
            if cancel.is_set():
                return
            yield pcm[start : start + block]

    # -- synthesis ----------------------------------------------------------
    def _synthesize_to_wav(self, text: str) -> bytes:
        try:
            import pyttsx3
        except ImportError as exc:  # pragma: no cover - env specific
            raise TTSError("pyttsx3 is not installed. Run: pip install pyttsx3") from exc

        tmp = Path(tempfile.gettempdir()) / f"clearvoice_tts_{id(text):x}.wav"
        engine = None
        try:
            # A fresh engine per utterance: pyttsx3 engines do not survive
            # repeated runAndWait() calls reliably, especially off the main thread.
            engine = pyttsx3.init()
            self._configure(engine)
            engine.save_to_file(text, str(tmp))
            engine.runAndWait()
        except TTSError:
            raise
        except Exception as exc:  # pyttsx3 raises a grab-bag of driver errors
            raise TTSError(f"system TTS engine failed: {exc}") from exc
        finally:
            if engine is not None:
                try:
                    engine.stop()
                except Exception:
                    pass

        try:
            if not tmp.exists() or tmp.stat().st_size == 0:
                raise TTSError("system TTS wrote no audio file")
            return tmp.read_bytes()
        finally:
            tmp.unlink(missing_ok=True)

    def _configure(self, engine) -> None:
        if self.cfg.rate:
            engine.setProperty("rate", self.cfg.rate)
        if self.cfg.volume:
            engine.setProperty("volume", self.cfg.volume)
        if not self.cfg.voice:
            return
        wanted = self.cfg.voice.lower()
        for voice in engine.getProperty("voices"):
            if wanted in (voice.name or "").lower() or wanted in (voice.id or "").lower():
                engine.setProperty("voice", voice.id)
                return
        log.warning("TTS voice %r not found; using the default voice", self.cfg.voice)

    # -- WAV -> PCM16 mono at target rate -----------------------------------
    @staticmethod
    def _wav_to_pcm16_mono(wav_bytes: bytes, target_rate: int) -> bytes:
        import io

        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            rate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())

        if width != 2:
            raise TTSError(f"expected 16-bit audio from system TTS, got {width * 8}-bit")
        if not frames:
            return b""

        samples = list(struct.unpack(f"<{len(frames) // 2}h", frames))
        if channels > 1:
            samples = SystemTTSProvider._downmix(samples, channels)
        if rate != target_rate:
            samples = SystemTTSProvider._resample(samples, rate, target_rate)
        return struct.pack(f"<{len(samples)}h", *samples)

    @staticmethod
    def _downmix(samples: list[int], channels: int) -> list[int]:
        return [
            sum(samples[i : i + channels]) // channels
            for i in range(0, len(samples) - channels + 1, channels)
        ]

    @staticmethod
    def _resample(samples: list[int], src_rate: int, dst_rate: int) -> list[int]:
        """Linear interpolation. Good enough for speech, no dependencies."""
        if not samples:
            return samples
        out_len = max(1, round(len(samples) * dst_rate / src_rate))
        step = (len(samples) - 1) / max(out_len - 1, 1)
        out = []
        for i in range(out_len):
            pos = i * step
            left = int(pos)
            right = min(left + 1, len(samples) - 1)
            frac = pos - left
            out.append(int(samples[left] * (1 - frac) + samples[right] * frac))
        return out