"""P3.3 Text-to-speech: providers (config-selected) + TTSAdapter -> AudioOutputEvent."""

from .adapter import SynthesisResult, TTSAdapter, TTSConfig, load_tts_config
from .base import CancelToken, TTSError, TTSProvider
from .providers import available_providers, create_provider, register_provider
from . import system_tts  

__all__ = [
    "CancelToken", "SynthesisResult", "TTSAdapter", "TTSConfig", "TTSError", "TTSProvider",
    "available_providers", "create_provider", "load_tts_config", "register_provider",
    "system_tts"
]
