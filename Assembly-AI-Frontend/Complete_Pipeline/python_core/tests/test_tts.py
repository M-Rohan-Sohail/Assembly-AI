import copy
from dataclasses import replace

import pytest

from src.common import ConfigError
from src.tts import CancelToken, TTSAdapter, TTSError, TTSProvider, create_provider, load_tts_config
from src.tts.providers import HttpStreamingTTSProvider


@pytest.fixture
def cfg():
    return replace(load_tts_config(), retry_backoff_s=0.0)


def run(adapter, text, cancel=None, **kw):
    events = []
    result = adapter.synthesize("s1", "u1", text, events.append, cancel, **kw)
    return result, events


class FlakyProvider(TTSProvider):
    """Fails `fail_times` times before producing audio."""

    def __init__(self, fail_times, size):
        self.fail_times, self.calls, self.size = fail_times, 0, size

    def synthesize_stream(self, text, cancel):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise TTSError("boom")
        yield bytes(self.size)


class PartialThenFail(TTSProvider):
    def __init__(self, size):
        self.calls, self.size = 0, size

    def synthesize_stream(self, text, cancel):
        self.calls += 1
        yield bytes(self.size)
        raise TTSError("died mid-stream")


# ---------------------------------------------------------------- chunking (CP-11)
def test_text_becomes_sequenced_chunks_then_final(cfg, data):
    text = data["tts"]["text"]
    result, events = run(TTSAdapter(config=cfg), text)
    mock = cfg.providers["mock"]

    assert result.status == TTSAdapter.COMPLETED
    assert [e["sequence"] for e in events] == list(range(len(events)))
    assert events[-1]["is_final"] and events[-1]["type"] == cfg.event_types.final
    assert events[-1]["audio_chunk"] == b""
    assert all(e["type"] == cfg.event_types.chunk and not e["is_final"] for e in events[:-1])
    assert all(len(e["audio_chunk"]) == cfg.chunk_size_bytes for e in events[:-2])
    assert sum(len(e["audio_chunk"]) for e in events) == len(text) * mock["bytes_per_char"]
    assert {(e["session_id"], e["utterance_id"], e["version"]) for e in events} == {("s1", "u1", cfg.event_version)}


def test_empty_text_is_skipped(cfg):
    result, events = run(TTSAdapter(config=cfg), "   ")
    assert result.status == TTSAdapter.SKIPPED and events == []


def test_first_chunk_callback_runs_once_before_first_emit(cfg, data):
    order = []
    adapter = TTSAdapter(config=cfg)
    adapter.synthesize("s", "u", data["tts"]["text"], lambda e: order.append("emit"),
                       on_first_chunk=lambda: order.append("first"))
    assert order[:2] == ["first", "emit"] and order.count("first") == 1


# ---------------------------------------------------------------- failures
def test_retries_when_nothing_was_heard_yet(cfg, data):
    provider = FlakyProvider(data["tts"]["retry_fail_times_ok"], cfg.chunk_size_bytes)
    result, events = run(TTSAdapter(provider, cfg), data["tts"]["text"])
    assert result.status == TTSAdapter.COMPLETED and provider.calls == data["tts"]["retry_fail_times_ok"] + 1
    assert events[0]["sequence"] == 0  # no duplicate / skipped audio


def test_gives_up_after_max_retries(cfg, data):
    provider = FlakyProvider(data["tts"]["retry_fail_times_too_many"], cfg.chunk_size_bytes)
    with pytest.raises(TTSError):
        run(TTSAdapter(provider, cfg), data["tts"]["text"])
    assert provider.calls == cfg.max_retries + 1


def test_never_retries_after_audio_was_already_sent(cfg, data):
    provider = PartialThenFail(cfg.chunk_size_bytes)
    events = []
    with pytest.raises(TTSError):
        TTSAdapter(provider, cfg).synthesize("s", "u", data["tts"]["text"], events.append)
    assert provider.calls == 1 and len(events) == 1


def test_provider_with_no_audio_is_an_error(cfg, data):
    class Silent(TTSProvider):
        def synthesize_stream(self, text, cancel):
            return iter(())

    with pytest.raises(TTSError, match="no audio"):
        run(TTSAdapter(Silent(), replace(cfg, max_retries=0)), data["tts"]["text"])


# ---------------------------------------------------------------- cancellation
def test_cancel_before_start(cfg, data):
    token = CancelToken()
    token.set()
    result, events = run(TTSAdapter(config=cfg), data["tts"]["text"], token)
    assert result.status == TTSAdapter.CANCELLED and events == []


def test_cancel_mid_stream_stops_without_final(cfg):
    token = CancelToken()
    events = []

    def emit(e):
        events.append(e)
        token.set()  # listener interrupts after the first chunk

    result = TTSAdapter(config=cfg).synthesize("s", "u", "x" * 5000, emit, token)
    assert result.status == TTSAdapter.CANCELLED
    assert len(events) == 1 and not events[0]["is_final"]


# ---------------------------------------------------------------- provider registry
def test_unknown_provider_fails_loudly():
    with pytest.raises(ConfigError, match="Unknown TTS provider"):
        create_provider("does_not_exist", {})


# ---------------------------------------------------------------- generic HTTP provider
def _http_cfg(data, server):
    c = copy.deepcopy(data["tts"]["http_provider"])
    c["variables"]["port"] = str(server.port)
    return c


def test_http_provider_sends_configured_request_and_streams_audio(cfg, data, http_server, monkeypatch):
    t = data["tts"]
    monkeypatch.setenv(t["env_var"], t["env_value"])
    audio = bytes(range(256)) * (t["server_audio_bytes"] // 256 + 1)
    audio = audio[: t["server_audio_bytes"]]
    http_server.responder = lambda path, body: (200, audio)

    adapter = TTSAdapter(create_provider("http", _http_cfg(data, http_server)), cfg)
    result, events = run(adapter, t["text"])

    assert result.status == TTSAdapter.COMPLETED
    assert b"".join(e["audio_chunk"] for e in events) == audio
    req = http_server.requests[0]
    assert req["path"].startswith("/tts/v1") and "fmt=pcm" in req["path"]
    assert t["text"] in req["body"] and '"lang": "en"' in req["body"]
    assert req["headers"]["X-Api-Key"] == t["env_value"]  # secret came from the environment


def test_http_error_status_becomes_tts_error(cfg, data, http_server, monkeypatch):
    t = data["tts"]
    monkeypatch.setenv(t["env_var"], t["env_value"])
    http_server.responder = lambda path, body: (500, b"nope")
    adapter = TTSAdapter(create_provider("http", _http_cfg(data, http_server)), replace(cfg, max_retries=0))
    with pytest.raises(TTSError, match="500"):
        run(adapter, t["text"])


def test_http_provider_needs_secret_in_environment(data, http_server, monkeypatch):
    monkeypatch.delenv(data["tts"]["env_var"], raising=False)
    with pytest.raises(ConfigError, match="not set"):
        create_provider("http", _http_cfg(data, http_server))


def test_http_provider_needs_a_url(data):
    bad = copy.deepcopy(data["tts"]["http_provider"])
    bad["url"] = ""
    with pytest.raises(ConfigError, match="url"):
        HttpStreamingTTSProvider.from_dict(bad)
