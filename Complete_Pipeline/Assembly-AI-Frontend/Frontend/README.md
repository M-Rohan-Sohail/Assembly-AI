# ClearVoice 2.0 — Frontend

A minimal, functional web frontend for the ClearVoice 2.0 speech-repair pipeline (backend: `Complete_Pipeline/python_core` + `ts_intelligence`), built against `clearvoice_frontend_plan.pdf`.

Stack: Next.js 16 (App Router) + TypeScript + Tailwind CSS v4. No state library — plain React state/hooks, as the plan calls for.

## Getting started

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## What's here (maps to the plan's phases)

- **Phase 1 (MVP):** Record/Stop button, raw transcript panel, repaired transcript panel, status badge (`Idle / Listening / Repairing / Validating / Speaking`).
- **Phase 2:** Speaking indicator (waveform pulses green while TTS plays), validation-fallback flag (shows when a repair was rejected and the system fell back to safer/original text), collapsible session history.
- **Phase 3:** Settings panel (mic device selector, demo playback voice), copy-to-clipboard, replay button, mute toggle, clear-history button, responsive layout.

## Demo mode (no backend required)

The plan's Phase 0 — the Python orchestrator exposing a WebSocket/SSE endpoint — doesn't exist yet (it's currently CLI-only; see `Complete_Pipeline/python_core/src/main.py`). So this frontend runs in **demo mode** by default: it captures your real mic for the live waveform, then drives the exact same state machine the real backend will drive using a small set of scripted "messy → repaired" utterances (`src/lib/ws/demo-simulation.ts`), and speaks the result aloud using the browser's built-in `SpeechSynthesis` API instead of ElevenLabs audio.

## Pointing at the real backend

Once the orchestrator exposes a WebSocket endpoint, set it in `.env.local` (copy `.env.local.example`):

```
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws/session
```

With that set, Settings → Demo mode can be switched off and the app will connect for real. The wire contract the frontend expects is defined in `src/lib/ws/types.ts` and mirrors `python_core/src/contracts.py` 1:1 (`TranscriptEvent`, `RepairResult`, `AudioOutputEvent`), plus a couple of additions the frontend needs that aren't in contracts.py yet:

- `stage.update` — `{ type, session_id, utterance_id, stage }` where `stage` is one of `idle | listening | repairing | validating | speaking`. Lets the backend own the status badge directly instead of the frontend inferring it from other events.
- `validation.result` — `{ type, session_id, utterance_id, approved, reason, source, spoken_text }`. `reason` is one of `contracts.ValidationReason`'s values; `source` is which text was ultimately spoken (`repaired | safer | original`), matching `UtteranceResult.source` in `orchestrator.py`.
- Client → server audio is sent as JSON `audio.chunk` messages with base64-encoded PCM16/16kHz mono `payload_b64` (see `useMicCapture`), rather than raw binary WS frames, to keep the whole contract JSON-only for a fast v1. Swap to binary frames later if bandwidth becomes a concern.
- Server → client `audio.chunk`/`audio.final` carry `audio_chunk_b64` (base64 of the raw PCM16LE/16kHz bytes described in `tts/tts_config.json`'s `audio_format`), decoded and scheduled gaplessly via Web Audio API in `useSpeechPlayback`.

No other frontend code needs to change to switch from demo to live — `useClearVoiceSession` handles both paths.

## Design system

Tokens live in `src/app/globals.css`: a light theme by default (this is a consumer tool for non-technical users, not a terminal) with a `prefers-color-scheme: dark` variant. Semantic colors: `accent` (in-progress/listening), `profit` (approved/validated), `warning` (fell back to safer text), `loss` (errors).
