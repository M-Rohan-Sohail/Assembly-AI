"""Run the whole Person 3 pipeline offline:  python -m src.demo_pipeline

Mock STT transcripts -> mock LLM (some outputs deliberately WRONG) -> validator + fallback
-> mock TTS -> latency breakdown. Proves CP-9, CP-10, CP-12 and CP-13 without any API key.
"""

import json
import sys
from pathlib import Path

from src.metrics import LatencyTracker
from src.orchestrator import build_orchestrator

DEMO_PATH = Path(__file__).with_name("orchestrator") / "demo_transcripts.json"


def main(path: Path = DEMO_PATH) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    sid = data["session_id"]
    metrics = LatencyTracker()
    current = {"uid": None}

    def emit(event):
        # the player would call this when audio actually starts playing
        metrics.mark(sid, event["utterance_id"], "playback")

    errors = []
    overrides = {u["text"]: u["mock_repair"] for u in data["utterances"] if u["mock_repair"]}
    orch = build_orchestrator(
        emit, on_error=lambda *a: errors.append(a), mock_overrides=overrides, metrics=metrics
    )

    for i, u in enumerate(data["utterances"], 1):
        uid = f"utt-{i}"
        metrics.mark(sid, uid, "audio_received", at_ms=metrics.now_ms() - data["audio_lead_ms"])
        event = {
            "type": "transcript.final", "version": 1, "session_id": sid, "utterance_id": uid,
            "text": u["text"], "is_final": True, "confidence": 0.9, "start_ms": 0, "end_ms": 1000,
        }
        result = orch.process_utterance(event)
        print(f"\n[{uid}] heard  : {u['text']}")
        print(f"        LLM said: {u['mock_repair'] or '(safe cleanup)'}")
        print(f"        SPOKEN  : {result.spoken_text}   <- source: {result.source}")
        rejected = [f"{a.level}: {a.reason}" for a in result.attempts if a.reason not in (None, 'approved')]
        if rejected:
            print(f"        rejected: {', '.join(rejected)}")
        print("        " + result.report.format().replace("\n", "\n        "))

    orch.shutdown()
    if errors:
        print(f"\n{len(errors)} error(s) reported: {errors}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else DEMO_PATH)
