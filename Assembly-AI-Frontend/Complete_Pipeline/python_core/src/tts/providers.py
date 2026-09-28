"""TTS providers. Add a new one with @register_provider - no other code changes.

Providers are chosen and configured ONLY in tts_config.json:
  - "mock": fake audio, for tests / demos / running without any API key
  - "http": any REST text-to-speech endpoint that streams audio bytes back
            (URL, headers, body, query all come from config; secrets via ${ENV_VAR})
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator
from urllib import error, parse, request

from src.common import ConfigError, build, expand_env

from .base import CancelToken, TTSError, TTSProvider

_PROVIDERS: dict[str, Callable[[dict], TTSProvider]] = {}


def register_provider(name: str):
    def decorator(cls):
        _PROVIDERS[name] = cls.from_dict
        return cls
    return decorator


def available_providers() -> list[str]:
    return sorted(_PROVIDERS)


def create_provider(name: str, provider_config: dict) -> TTSProvider:
    if name not in _PROVIDERS:
        raise ConfigError(f"Unknown TTS provider '{name}'. Available: {available_providers()}")
    return _PROVIDERS[name](provider_config)


# ---------------------------------------------------------------------------
# Mock
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MockTTSConfig:
    bytes_per_char: int
    block_bytes: int
    delay_s: float


@register_provider("mock")
class MockTTSProvider(TTSProvider):
    """Deterministic fake audio: silence whose length depends on the text."""

    def __init__(self, cfg: MockTTSConfig):
        self.cfg = cfg

    @classmethod
    def from_dict(cls, data: dict) -> "MockTTSProvider":
        return cls(build(MockTTSConfig, data, "tts.providers.mock"))

    def synthesize_stream(self, text: str, cancel: CancelToken) -> Iterator[bytes]:
        remaining = len(text) * self.cfg.bytes_per_char
        while remaining > 0:
            if cancel.is_set():
                return
            if self.cfg.delay_s:
                time.sleep(self.cfg.delay_s)
            size = min(self.cfg.block_bytes, remaining)
            yield bytes(size)
            remaining -= size


# ---------------------------------------------------------------------------
# Generic HTTP streaming provider
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class HttpTTSConfig:
    url: str  # may contain {variables}
    method: str
    headers: dict  # values may contain ${ENV_VAR}
    query: dict
    body: dict  # any JSON; the text_placeholder inside strings is replaced by the text
    variables: dict  # values for {name} in url
    text_placeholder: str
    timeout_s: float
    read_block_bytes: int


def _substitute(value: Any, placeholder: str, text: str) -> Any:
    if isinstance(value, str):
        return value.replace(placeholder, text)
    if isinstance(value, list):
        return [_substitute(v, placeholder, text) for v in value]
    if isinstance(value, dict):
        return {k: _substitute(v, placeholder, text) for k, v in value.items()}
    return value


@register_provider("http")
class HttpStreamingTTSProvider(TTSProvider):
    def __init__(self, cfg: HttpTTSConfig):
        if not cfg.url:
            raise ConfigError("tts.providers.http.url is empty - set it in tts_config.json")
        self.cfg = cfg
        # secrets are read from the environment here, not stored in the JSON
        self._headers = expand_env(cfg.headers)
        self._variables = expand_env(cfg.variables)

    @classmethod
    def from_dict(cls, data: dict) -> "HttpStreamingTTSProvider":
        return cls(build(HttpTTSConfig, data, "tts.providers.http"))

    def _request(self, text: str) -> request.Request:
        cfg = self.cfg
        url = cfg.url.format(**self._variables)
        if cfg.query:
            url += "?" + parse.urlencode(expand_env(cfg.query))
        body = _substitute(cfg.body, cfg.text_placeholder, text)
        data = json.dumps(body).encode("utf-8") if body else None
        return request.Request(url, data=data, headers=self._headers, method=cfg.method)

    def synthesize_stream(self, text: str, cancel: CancelToken) -> Iterator[bytes]:
        try:
            with request.urlopen(self._request(text), timeout=self.cfg.timeout_s) as resp:
                while not cancel.is_set():
                    block = resp.read(self.cfg.read_block_bytes)
                    if not block:
                        return
                    yield block
        except error.HTTPError as exc:
            raise TTSError(f"TTS HTTP {exc.code}: {exc.reason}") from exc
        except (error.URLError, TimeoutError, OSError) as exc:
            raise TTSError(f"TTS request failed: {exc}") from exc
