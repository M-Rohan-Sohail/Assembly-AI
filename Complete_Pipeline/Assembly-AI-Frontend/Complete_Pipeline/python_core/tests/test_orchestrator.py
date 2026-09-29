import copy
import time
from dataclasses import replace

import pytest

from _data import DATA
from src.common import ConfigError
from src.metrics import LatencyTracker
from src.orchestrator import (
    HttpRepairClient, MockRepairClient, RepairError, SessionOrchestrator, Stage, Status, create_repair_client,
)
from src.orchestrator.orchestrator import load_orchestrator_config
from src.orchestrator.repair_clients import HttpRepairConfig, RepairConfig, load_repair_config
from src.tts import TTSAdapter, TTSError, TTSProvider, load_tts_config
from src.validation import MeaningValidator
from src.validation.fallback import FallbackEngine


# ---------------------------------------------------------------- fakes
class RecordingTTS(TTSProvider):
    """Real TTSAdapter, fake provider: remembers exactly which text the listener would hear."""

    def __init__(self, fail_first=0):
        self.spoken, self.fail_first, self.calls = [], fail_first, 0

    def synthesize_stream(self, text, cancel):
        self.calls += 1
        if self.calls <= self.fail_first:
            raise TTSError("tts down")
        self.spoken.append(text)
        yield b"audio"


class StaticRepair:
    def __init__(self, table):
        self.table = table

    def repair(self, event):
        text = event["text"]
        return {"session_id": event["session_id"], "utterance_id": event["utterance_id"],
                "original_text": text, "repaired_text": self.table.get(text, text)}


class CrashingRepair:
    def repair(self, event):
        raise RuntimeError("LLM exploded")


class SlowRepair:
    def __init__(self, delay):
        self.delay = delay

    def repair(self, event):
        time.sleep(self.delay)
        return {"repaired_text": "never used"}


def make(repair, tts=None, config=None, **kw):
    tts = tts or RecordingTTS()
    events, errors = [], []
    tts_cfg = replace(load_tts_config(), retry_backoff_s=0.0, max_retries=0)
    orch = SessionOrchestrator(
        repair=repair,
        fallback=FallbackEngine(MeaningValidator()),
        tts=TTSAdapter(tts, tts_cfg),
        metrics=LatencyTracker(),
        emit=events.append,
        config=config,
        on_error=lambda *a: errors.append(a),
        **kw,
    )
    return orch, tts, events, errors


@pytest.fixture
def cleanup():
    made = []
    yield made.append
    for o in made:
        o.shutdown()


# ---------------------------------------------------------------- the core flow (CP-12)
@pytest.mark.parametrize("case", DATA["orchestrator_cases"], ids=lambda c: c["name"])
def test_utterance_flow(case, make_event, cleanup):
    orch, tts, events, errors = make(StaticRepair({case["text"]: case["repair"]}))
    cleanup(orch)
    result = orch.process_utterance(make_event(text=case["text"]))

    assert result.status == Status.SPOKEN
    assert result.spoken_text == case["spoken"] and result.source == case["source"]
    assert tts.spoken == [case["spoken"]]  # what the listener hears
    assert events and events[-1]["is_final"]
    assert errors == []


def test_report_contains_the_orchestrators_timestamps(make_event, cleanup):  # CP-13
    orch, _, _, _ = make(StaticRepair({}))
    cleanup(orch)
    result = orch.process_utterance(make_event(text="I want it."))
    m = load_orchestrator_config().marks
    for name in [*m.on_receive, m.llm_start, m.llm_end, m.validation, m.tts_first_chunk]:
        assert name in result.report.marks


def test_known_entities_are_protected(data, make_event, cleanup):
    c = data["entity_case"]
    orch, tts, _, _ = make(StaticRepair({c["text"]: c["repair"]}), known_entities_for=lambda sid: c["known"])
    cleanup(orch)
    orch.process_utterance(make_event(text=c["text"]))
    assert tts.spoken == [c["spoken"]]


@pytest.mark.parametrize("case", DATA["ignored_events"], ids=lambda c: c["name"])
def test_non_final_or_empty_transcripts_are_ignored(case, make_event, cleanup):
    orch, tts, events, _ = make(StaticRepair({}))
    cleanup(orch)
    result = orch.process_utterance(make_event(type=case["type"], text=case["text"]))
    assert result.status == Status.IGNORED and tts.calls == 0 and events == []


# ---------------------------------------------------------------- failures never stop the session
def test_repair_crash_falls_back_to_safe_text(make_event, cleanup):
    orch, tts, _, errors = make(CrashingRepair())
    cleanup(orch)
    result = orch.process_utterance(make_event(text="I I I want um to go."))
    assert result.status == Status.SPOKEN and result.source == "safer"
    assert tts.spoken == ["I want to go."]
    assert [e[0] for e in errors] == [Stage.REPAIR]


def test_repair_timeout_falls_back(data, make_event, cleanup):
    cfg = replace(load_orchestrator_config(), repair_timeout_s=data["timeout_s"])
    orch, tts, _, errors = make(SlowRepair(data["slow_repair_delay_s"]), config=cfg)
    cleanup(orch)
    result = orch.process_utterance(make_event(text="Hello there."))
    assert result.source == "original" and tts.spoken == ["Hello there."]
    assert errors and errors[0][0] == Stage.REPAIR and "longer than" in str(errors[0][3])


def test_fallback_crash_still_speaks_original(make_event, cleanup):
    orch, tts, _, errors = make(StaticRepair({}))
    cleanup(orch)
    orch._fallback.resolve = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("validator bug"))
    result = orch.process_utterance(make_event(text="I need 500 dollars."))
    assert result.spoken_text == "I need 500 dollars." and result.source == "original"
    assert [e[0] for e in errors] == [Stage.FALLBACK]


def test_tts_failure_is_reported_and_next_utterance_works(make_event, cleanup):
    orch, tts, _, errors = make(StaticRepair({}), tts=RecordingTTS(fail_first=1))
    cleanup(orch)
    first = orch.process_utterance(make_event(utterance_id="u1", text="Hello there."))
    second = orch.process_utterance(make_event(utterance_id="u2", text="Hello again."))
    assert first.status == Status.TTS_FAILED and [e[0] for e in errors] == [Stage.TTS]
    assert second.status == Status.SPOKEN and tts.spoken == ["Hello again."]


def test_broken_error_handler_does_not_break_the_pipeline(make_event, cleanup):
    orch, tts, _, _ = make(CrashingRepair())
    cleanup(orch)
    orch._on_error = lambda *a: 1 / 0
    assert orch.process_utterance(make_event(text="Hello there.")).status == Status.SPOKEN


# ---------------------------------------------------------------- sessions
def test_submit_keeps_utterances_in_order(data, make_event, cleanup):
    orch, tts, _, _ = make(StaticRepair({}))
    cleanup(orch)
    futures = [orch.submit(make_event(utterance_id=f"u{i}", text=t)) for i, t in enumerate(data["ordering"]["texts"])]
    assert [f.result(timeout=5).spoken_text for f in futures] == data["ordering"]["texts"]
    assert tts.spoken == data["ordering"]["texts"]


def test_cancel_speech_and_close_session(make_event, cleanup):
    orch, tts, _, _ = make(StaticRepair({}))
    cleanup(orch)
    orch.open_session("s1")
    orch.cancel_speech("s1")  # barge-in must not poison the session
    assert orch.process_utterance(make_event(text="Hello there.")).status == Status.SPOKEN
    orch.close_session("s1")
    assert "s1" not in orch._sessions
    assert orch.process_utterance(make_event(text="Hello again.")).status == Status.SPOKEN  # reopens


# ---------------------------------------------------------------- repair clients (Person 2 bridge)
def test_mock_repair_client_shape(make_event):
    fallback = FallbackEngine(MeaningValidator())
    client = create_repair_client(rewriter=fallback.rewriter)
    assert isinstance(client, MockRepairClient)
    result = client.repair(make_event(text="I I I want um it."))
    assert result["repaired_text"] == "I want it."
    assert {"session_id", "utterance_id", "original_text", "repaired_text"} <= result.keys()


def _http_client(data, server):
    cfg = copy.deepcopy(data["http_repair"]["config"])
    cfg["url"] = cfg["url"].format(port=server.port)
    from src.common import build
    return HttpRepairClient(build(HttpRepairConfig, cfg, "test"))


def test_http_repair_client_translates_between_camel_and_snake(data, make_event, http_server):
    import json
    http_server.responder = lambda path, body: (200, json.dumps(data["http_repair"]["server_response"]).encode())
    result = _http_client(data, http_server).repair(make_event(text="I I want it."))

    sent = json.loads(http_server.requests[0]["body"])
    assert "utteranceId" in sent and "utterance_id" not in sent  # TypeScript side gets camelCase
    assert result["repaired_text"] == "I want it." and result["session_id"] == "s1"  # we get snake_case back


def test_http_repair_client_errors_become_repair_error(data, make_event, http_server):
    import json
    client = _http_client(data, http_server)
    http_server.responder = lambda path, body: (500, b"boom")
    with pytest.raises(RepairError, match="500"):
        client.repair(make_event(text="x"))
    http_server.responder = lambda path, body: (200, json.dumps(data["http_repair"]["incomplete_response"]).encode())
    with pytest.raises(RepairError, match="missing"):
        client.repair(make_event(text="x"))
    http_server.responder = lambda path, body: (200, b"not json")
    with pytest.raises(RepairError):
        client.repair(make_event(text="x"))


def test_unreachable_repair_service_is_a_repair_error(data, make_event):
    from src.common import build
    cfg = copy.deepcopy(data["http_repair"]["config"])
    cfg["url"] = cfg["url"].format(port=1)  # nothing listens here
    with pytest.raises(RepairError):
        HttpRepairClient(build(HttpRepairConfig, cfg, "test")).repair(make_event(text="x"))


def test_unknown_repair_provider_fails_loudly():
    with pytest.raises(ConfigError):
        create_repair_client(RepairConfig(provider="nope", providers={}))
