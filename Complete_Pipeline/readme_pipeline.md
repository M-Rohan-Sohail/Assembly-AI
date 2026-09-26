# ClearVoice 2.0 — Pipeline Architecture & Engineering Report

## Overview
ClearVoice 2.0 is an advanced real-time speech repair pipeline designed to take raw, messy human speech (containing stutters, filler words, and restarts), intelligently repair it into a clean transcript, rigorously validate the repair to prevent hallucinations, and synthesize it back into spoken audio.

To utilize the best tools for each job, the project employs a **polyglot microservice architecture**:
- **Python** handles the low-latency hardware integrations (Audio I/O, VAD, STT, TTS) and orchestration.
- **Node.js / TypeScript** handles the complex LLM intelligence, prompt engineering, and context management.

---

## How It Works (End-to-End Flow)
1. **Audio Ingestion:** `audio_recorder.py` captures raw microphone audio in real-time.
2. **VAD & Endpointing:** `endpointing.py` uses Silero VAD to detect when the user is speaking and when they pause. It applies a custom threshold to avoid cutting the user off during short mid-sentence pauses.
3. **STT:** `assemblyai_service.py` streams the audio chunks to AssemblyAI via websockets, receiving real-time partial and final transcripts.
4. **Handoff (Orchestration):** When an utterance is finalized, the Python Orchestrator sends a `TranscriptEvent` payload over HTTP to the Node.js Intelligence Server.
5. **Intelligence & Repair:** The Node.js server analyzes the dysfluencies, appends conversation history and user profile data, and queries **Groq's Qwen model** to repair the text.
6. **Validation:** The returned `RepairResult` is sent back to Python, where the **Meaning Validator** deterministically checks that the LLM did not alter critical facts (like numbers, dates, or negations).
7. **Playback:** If approved, the repaired text is sent to the TTS engine and played back to the user.

---

## Workstream Breakdown

### Person 1 (P1) — Speech Input & STT
**Stack:** Python, PyAudio, PyTorch (Silero VAD), AssemblyAI
**Location:** `python_core/src/`
- **Audio Ingestion:** Manages audio chunking and sequence numbering.
- **Voice Activity Detection:** Uses the `silero-vad` model to accurately distinguish human speech from background noise.
- **Custom Endpointing:** Implements logic to ignore short stutters and only terminate an utterance upon a definitive pause.
- **AssemblyAI Realtime:** Maintains a persistent WebSocket connection to AssemblyAI's Streaming API.

### Person 2 (P2) — Intelligence / LLM
**Stack:** TypeScript, Node.js, Express, Groq API
**Location:** `ts_intelligence/src/`
- **Transcript Analyzer (`analyzer.ts`):** Deterministically labels words as `normal`, `filler`, `restart`, or `possible_repetition`. Crucially, it identifies *intentional* emphasis (e.g., "no, no, I really mean it").
- **Conversation Context (`context.ts`):** Maintains a ring-buffer of the last 6 utterances to give the LLM context of the ongoing conversation, preventing memory leaks over long sessions.
- **User Profile (`userProfile.ts`):** Injects user-specific vocabulary and deterministically patches known STT recognition errors *before* the LLM sees them.
- **LLM Repair Engine (`llmRepair.ts`):** Prompts the Groq model to repair the dysfluencies while strictly adhering to 9 hard rules (e.g., "Never invent facts", "Never change negation"). It forces structured JSON output and safely handles timeouts or low-confidence generations.

### Person 3 (P3) — Validation, TTS & Orchestration
**Stack:** Python, ElevenLabs API
**Location:** `python_core/src/orchestrator/` & `validation/`
- **Meaning Validator:** A robust, regex-and-heuristic-based engine that compares the original STT text against the LLM's repaired text. It outright rejects repairs that change numbers, dates, pronouns, or strip negations (like "not").
- **Fallback Engine:** If the Validator catches a hallucination, this engine intercepts the failure and falls back to a safer output or the original raw transcript, ensuring the user always hears *something* accurate.
- **Session Orchestrator:** The glue that ties P1, P2, and P3 together. It manages the HTTP calls to the Node.js server and ensures that an error in any individual component (like an AssemblyAI timeout or a Groq API failure) doesn't kill the entire session.
- **TTS Adapter:** Synthesizes the final approved text using ElevenLabs cloud TTS via HTTP streaming.

---

## How to Run It

### Prerequisites
- Python 3.10+
- Node.js (v18+)
- Active API keys for **AssemblyAI**, **Groq**, and **ElevenLabs**

### 1. Environment Setup
At the root of `Complete_Pipeline`, create a `.env` file containing:
```env
ASSEMBLYAI_API_KEY=your_assemblyai_key_here
GROQ_API_KEY=your_groq_key_here
ELEVENLABS_API_KEY=your_elevenlabs_api_key_here
ELEVENLABS_VOICE_ID=your_elevenlabs_voice_id_here
```

### 2. Install Dependencies
**Node.js (P2):**
```bash
cd Complete_Pipeline/ts_intelligence
npm install
```

**Python (P1 & P3):**
Ensure you have the required C-headers for audio (`sudo apt-get install python3.12-dev portaudio19-dev` on Ubuntu), then:
```bash
cd Complete_Pipeline
pip install -r python_core/requirements.txt
```

### 3. Start the Pipeline
A master orchestrator script has been provided to automatically launch both the Node.js server in the background and the Python STT listener in the foreground.

Run from the root of `Complete_Pipeline`:
```bash
python main.py
```

### Usage
- The terminal will prompt you to press `M` and hit Enter to start recording.
- Speak naturally with stutters or pauses (e.g., *"I want... um... I want to book a flight for Friday—actually Thursday."*).
- Press `M` and Enter again to stop.
- The pipeline will output the raw transcript, send it to the Node.js server for repair, validate it, and play the clean version back via audio. 
- *Note: Press `Ctrl+C` at any time to gracefully terminate both the Python and Node.js processes.*
