# ClearVoice 2.0 — Person 2: Intelligence / LLM

Implements the full **Person 2** workstream from the ClearVoice 2.0 Core
Task Board: `TranscriptEvent → understanding → RepairResult`.

## What's inside

| Task Board Item | File | Checkpoint |
|---|---|---|
| P2.1 Transcript Analyzer | `src/analyzer.ts` | CP-5 |
| P2.2 Conversation Context | `src/context.ts` | CP-6 |
| P2.3 User Profile | `src/userProfile.ts` | CP-7 |
| P2.4 LLM Repair Engine | `src/llmRepair.ts` | CP-8 |
| Orchestration glue | `src/pipeline.ts` (`Person2Pipeline`) | — |
| Public exports | `src/index.ts` | — |
| Tests / mock data | `src/tests/` | CP-5, CP-8 |

## Install

```bash
npm install
```

## Run tests (no API key needed)

```bash
npm run test:analyzer   # CP-5: 18 curated dysfluency examples
npm run test:pipeline   # CP-8: 30 mock transcripts -> structured RepairResults
npm run test:all
```

Both test scripts run **fully offline** — `testPipeline.ts` injects a small
deterministic mock "LLM" via `LLMRepairEngine`'s `mockCompletionFn` option so
you (and Person 1/Person 3, per the task board's "nobody should wait" rule)
can integrate against this module on Day 2–4 without a live API key.

## Wiring up the real Claude API

Set an API key and drop the mock:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

```ts
import { Person2Pipeline } from "./src/pipeline";

const pipeline = new Person2Pipeline(); // no mockCompletionFn -> uses real Claude API
const result = await pipeline.repair(transcriptEvent);
```

No other code changes needed — `LLMRepairEngine` and `Person2Pipeline` don't
change shape whether they're backed by the mock or the real API.

## Integration point for Person 3 (Orchestrator, P3.4)

This matches the exact example in the task board's P3.4 section:

```ts
import { Person2Pipeline } from "./person2/src/pipeline";

const intelligence = new Person2Pipeline();

async function processUtterance(event: TranscriptEvent) {
  const repair = await intelligence.repair(event);
  const validation = validator.validate(repair.originalText, repair.repairedText);
  const text = validation.approved ? repair.repairedText : repair.originalText;
  await tts.synthesizeStream(text, emitAudioChunk);
}
```

`Person2Pipeline.repair()` returns a `RepairResult` matching the frozen
shared contract exactly (`type`, `version`, `sessionId`, `utteranceId`,
`originalText`, `repairedText`, `confidence`, `changes`) — ready to hand to
Person 3's Validator with zero adaptation.

## How the 9 core LLM rules are enforced

The system prompt in `llmRepair.ts` states all 9 rules explicitly and gives
worked examples. On top of that, the engine has **defense in depth** so a
single bad LLM response can never reach the Validator un-caught:

1. **Structured output required** — LLM must return JSON matching
   `LLMRepairOutputSchema`. Malformed JSON or a schema mismatch triggers
   one retry, then a safe fallback (Rule 9: return original text).
2. **Timeout** — capped at 4s (configurable) so a slow LLM call never stalls
   the real-time pipeline; on timeout, falls back to the original text
   immediately (no retry burned).
3. **Explicit uncertainty** — if the LLM sets `uncertain: true` or reports
   `confidence < 0.5`, the engine ignores the "repaired" text and returns
   the original, unmodified.
4. **Hard-rule guard** — even a well-formed, confident response is checked
   for invented/changed numbers before being trusted (a second, independent
   check beyond just asking the LLM nicely).

This module is deliberately **not** the final safety authority — per the
task board's dependency map, Person 3's Meaning Validator (P3.1) is the
last line of defense before TTS. `Person2Pipeline` output should always be
run through validation downstream.

## Design notes / assumptions made

- **Analyzer is rule-based, not LLM-based.** It's a fast, deterministic
  pre-pass that hands the LLM cheap structured signal (segments +
  labels), and it works with zero external dependency, satisfying CP-5
  standalone.
- **Intentional vs. dysfluent repetition** ("I really, really like this")
  is resolved primarily by the LLM (given full sentence context), not the
  analyzer — the analyzer only avoids mislabeling obviously-emphatic
  repetition as `filler`, per the task board's explicit warning against
  "automatically delete every repetition."
- **Context and User Profile are in-memory** (`Map`-based), matching the
  task board's "keep it simple for the 2-week MVP" note for the profile.
  Swapping in Redis/Postgres later only touches `context.ts` /
  `userProfile.ts` internals — the public methods stay the same.
- **`userId` defaults to `sessionId`** when no separate identity system is
  wired up yet, so the pipeline is usable immediately without auth.
- Model used for the real API path: `claude-sonnet-4-6` (per this
  environment's Claude-in-Claude convention) — swap the `MODEL` constant
  in `llmRepair.ts` if your deployment target differs.

## Directory structure

```
clearvoice-person2/
├── package.json
├── tsconfig.json
├── README.md
└── src/
    ├── types.ts          # All shared data contracts (frozen Day 1)
    ├── analyzer.ts        # P2.1
    ├── context.ts         # P2.2
    ├── userProfile.ts     # P2.3
    ├── llmRepair.ts        # P2.4
    ├── pipeline.ts         # Person2Pipeline (glues 2.1-2.4 together)
    ├── index.ts            # public exports
    └── tests/
        ├── mockData.ts     # CP-5 + CP-8 fixtures
        ├── testAnalyzer.ts # CP-5
        └── testPipeline.ts # CP-8
```
