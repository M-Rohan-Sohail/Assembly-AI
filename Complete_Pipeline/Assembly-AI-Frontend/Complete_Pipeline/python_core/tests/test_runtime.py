import threading
import time
import wave
from dataclasses import replace

import pytest

from src.common import ConfigError
from src.orchestrator.runtime import Person3Runtime, load_runtime_config
from src.orchestrator.sinks import MultiSink, SpeakerSink, WavFileSink, audio_format_from, create_sink
from src.orchestrator import Status
from src.tts import TTSAdapter, load_tts_config


@pytest.fixture
def fmt():
    return audio_format_from(load_tts_config().audio_format)


def speak(text, emit, session="s1", utterance="u1"):
    TTSAdapter(config=load_tts_config()).synthesize(session, utterance, text, emit)


def wait_until(condition, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.01)
    return False


# ---------------------------------------------------------------- sinks
def test_wav_sink_writes_a_valid_file(tmp_path, data, fmt):
    cfg = load_runtime_config()
    sink = WavFileSink(tmp_path, cfg.wav_name_pattern, fmt)
    text = data["runtime"]["text"]
    speak(text, sink)

    assert sink.last_path == tmp_path / cfg.wav_name_pattern.format(session_id="s1", utterance_id="u1")
    with wave.open(str(sink.last_path)) as wf:
        assert (wf.getnchannels(), wf.getsampwidth(), wf.getframerate()) == (fmt.channels, fmt.sample_width_bytes, fmt.sample_rate)
        expected_bytes = len(text) * load_tts_config().providers["mock"]["bytes_per_char"]
        assert wf.getnframes() * fmt.sample_width_bytes * fmt.channels == expected_bytes


def test_wav_sink_discards_unfinished_utterances(tmp_path, data, fmt):
    sink = WavFileSink(tmp_path, load_runtime_config().wav_name_pattern, fmt)
    events = []
    speak(data["runtime"]["text"], events.append)
    sink(events[0])  # never receives the final chunk (e.g. cancelled)
    sink.close()
    assert list(tmp_path.iterdir()) == []


class FakePyAudio:
    """Stands in for the pyaudio module (no sound card needed)."""

    opened, writes, closed = [], [], []

    class PyAudio:
        def get_format_from_width(self, width):
            return ("fmt", width)

        def open(self, **kwargs):
            FakePyAudio.opened.append(kwargs)
            return FakePyAudio.Stream()

        def terminate(self):
            FakePyAudio.closed.append("pa")

    class Stream:
        def write(self, data):
            FakePyAudio.writes.append(data)

        def stop_stream(self):
            FakePyAudio.closed.append("stop")

        def close(self):
            FakePyAudio.closed.append("close")


def test_speaker_sink_opens_lazily_once_and_writes_audio(data, fmt):
    FakePyAudio.opened, FakePyAudio.writes, FakePyAudio.closed = [], [], []
    sink = SpeakerSink(fmt, pyaudio_module=FakePyAudio)
    assert FakePyAudio.opened == []  # nothing opened before the first audio

    text = data["runtime"]["text"]
    speak(text, sink)
    assert len(FakePyAudio.opened) == 1
    assert FakePyAudio.opened[0] == {
        "format": ("fmt", fmt.sample_width_bytes), "channels": fmt.channels, "rate": fmt.sample_rate, "output": True,
    }
    assert sum(map(len, FakePyAudio.writes)) == len(text) * load_tts_config().providers["mock"]["bytes_per_char"]
    sink.close()
    assert FakePyAudio.closed == ["stop", "close", "pa"]


def test_multi_sink_one_failure_does_not_starve_the_others():
    got = []

    def broken(event):
        raise RuntimeError("no speaker")

    sink = MultiSink([broken, got.append])
    with pytest.raises(RuntimeError):
        sink({"x": 1})
    assert got == [{"x": 1}]


def test_unknown_sink_name_fails_loudly(data, fmt):
    with pytest.raises(ConfigError, match="Unknown sink"):
        create_sink([data["sinks"]["unknown"]], fmt, ".", "x.wav")


# ---------------------------------------------------------------- runtime (what main.py uses)
def make_runtime(tmp_path, **kw):
    cfg = replace(load_runtime_config(), sinks=["wav"], wav_output_dir=str(tmp_path))
    return Person3Runtime(config=replace(cfg, **kw.pop("cfg", {})), **kw)


def test_runtime_end_to_end(tmp_path, data, make_event, capsys):
    r = data["runtime"]
    runtime = make_runtime(tmp_path)
    try:
        result = runtime.submit(make_event(text=r["text"])).result(timeout=r["wait_timeout_s"])
        assert wait_until(lambda: not runtime.is_speaking, r["wait_timeout_s"])
    finally:
        runtime.close()

    assert result.status == Status.SPOKEN and result.spoken_text == r["expected_spoken"]
    assert result.source == r["expected_source"]
    assert len(list(tmp_path.glob("*.wav"))) == 1
    assert load_runtime_config().playback_mark in runtime.metrics.report("s1", "u1").marks
    out = capsys.readouterr().out
    assert f"[SPOKEN:{r['expected_source']}] {r['expected_spoken']}" in out
    assert load_runtime_config().print_latency and "TTFCA" in out


def test_runtime_is_speaking_while_busy(tmp_path, data, make_event):
    r = data["runtime"]
    release = threading.Event()

    def slow_sink(event):
        release.wait(r["wait_timeout_s"])

    runtime = Person3Runtime(config=make_runtime(tmp_path).config, sink=slow_sink)
    try:
        runtime.submit(make_event(text=r["text"]))
        assert runtime.is_speaking
        release.set()
        assert wait_until(lambda: not runtime.is_speaking, r["wait_timeout_s"])
    finally:
        release.set()
        runtime.close()


def test_broken_player_is_reported_and_next_utterance_still_plays(tmp_path, data, make_event, capsys):
    r = data["runtime"]
    heard = []

    def flaky_sink(event):
        if event["utterance_id"] == r["failing_utterance"]:
            raise OSError("no audio device")
        heard.append(event)

    runtime = Person3Runtime(config=make_runtime(tmp_path).config, sink=flaky_sink)
    try:
        first = runtime.submit(make_event(utterance_id=r["utterances"][0], text=r["text"])).result(timeout=r["wait_timeout_s"])
        second = runtime.submit(make_event(utterance_id=r["utterances"][1], text=r["text"])).result(timeout=r["wait_timeout_s"])
    finally:
        runtime.close()
    assert first.status == Status.PLAYBACK_FAILED and second.status == Status.SPOKEN
    assert heard and "PLAYBACK ERROR" in capsys.readouterr().out


def test_submit_never_raises_on_a_bad_event(tmp_path, capsys):
    runtime = make_runtime(tmp_path)
    try:
        assert runtime.submit({"text": "no ids here"}) is None  # missing session_id / utterance_id
    finally:
        runtime.close()
    assert "SUBMIT ERROR" in capsys.readouterr().out
