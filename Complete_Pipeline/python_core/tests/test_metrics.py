from dataclasses import replace

import pytest

from src.metrics import LatencyTracker, load_metrics_config


def fill(tracker, marks, sid="s", uid="u"):
    for name, at in marks.items():
        tracker.mark(sid, uid, name, at_ms=at)


def test_full_breakdown(data):  # CP-13
    m = data["metrics"]
    tracker = LatencyTracker()
    fill(tracker, m["marks"])
    report = tracker.report("s", "u")
    assert dict(report.stages) == m["expected_stages"]
    assert report.total_ms == m["expected_total"]
    assert report.total_label in report.format()


def test_missing_marks_show_placeholder_and_total_falls_back(data):
    m = data["metrics"]
    tracker = LatencyTracker()
    marks = {k: v for k, v in m["marks"].items() if k != "playback"}
    fill(tracker, marks)
    report = tracker.report("s", "u")
    assert dict(report.stages)["Playback"] is None
    assert report.total_ms == m["expected_total_without_playback"]
    assert load_metrics_config().missing_text in report.format()


def test_first_value_wins_unless_overwrite(data):
    tracker = LatencyTracker()
    tracker.mark("s", "u", "stt_final", at_ms=1)
    tracker.mark("s", "u", "stt_final", at_ms=2)
    assert tracker.report("s", "u").marks["stt_final"] == 1
    tracker.mark("s", "u", "stt_final", at_ms=3, overwrite=True)
    assert tracker.report("s", "u").marks["stt_final"] == 3


def test_unknown_mark_name_is_rejected():
    with pytest.raises(ValueError, match="Unknown mark"):
        LatencyTracker().mark("s", "u", "not_a_mark")


def test_memory_is_bounded(data):
    m = data["metrics"]
    tracker = LatencyTracker(replace(load_metrics_config(), max_tracked_utterances=m["bound"]))
    first_mark = load_metrics_config().marks[0]
    for i in range(m["utterances_to_add"]):
        tracker.mark("s", f"u{i}", first_mark, at_ms=i)
    kept = [i for i in range(m["utterances_to_add"]) if tracker.report("s", f"u{i}").marks]
    assert kept == list(range(m["utterances_to_add"] - m["bound"], m["utterances_to_add"]))


def test_stages_come_from_config(data):
    cfg = replace(load_metrics_config(), stages=load_metrics_config().stages[:1])
    tracker = LatencyTracker(cfg)
    fill(tracker, data["metrics"]["marks"])
    assert [label for label, _ in tracker.report("s", "u").stages] == [cfg.stages[0].label]
