import type { RepairChange, ValidationReason } from "./types";

/**
 * Client-only stand-in for the real orchestrator pipeline, used when
 * NEXT_PUBLIC_WS_URL is unset or unreachable. Backend Phase 0 (a WebSocket/
 * SSE endpoint on the Python orchestrator) doesn't exist yet, so this keeps
 * the UI fully demoable: it drives the exact same state machine the real
 * backend will drive, using scripted text instead of AssemblyAI/Groq output.
 * TTS playback in this mode uses the browser's SpeechSynthesis API instead
 * of ElevenLabs audio bytes.
 */
export interface DemoScript {
  raw: string;
  repaired: string;
  changes: RepairChange[];
  approved: boolean;
  reason: ValidationReason;
}

export const DEMO_SCRIPTS: DemoScript[] = [
  {
    raw: "so um i was thinking we should we should meet at, at three pm tomorrow",
    repaired: "I was thinking we should meet at three PM tomorrow.",
    changes: [
      { type: "filler_removed", original: "so um", replacement: "" },
      { type: "repetition_removed", original: "we should we should", replacement: "we should" },
    ],
    approved: true,
    reason: "approved",
  },
  {
    raw: "can you can you send me the the report by uh friday",
    repaired: "Can you send me the report by Friday?",
    changes: [
      { type: "repetition_removed", original: "can you can you", replacement: "can you" },
      { type: "filler_removed", original: "the the", replacement: "the" },
    ],
    approved: true,
    reason: "approved",
  },
  {
    raw: "the the meeting got moved to like nine thirty i think not not ten",
    repaired: "The meeting got moved to nine thirty, not ten.",
    changes: [
      { type: "repetition_removed", original: "the the", replacement: "the" },
      { type: "repetition_removed", original: "not not", replacement: "not" },
    ],
    approved: true,
    reason: "approved",
  },
  {
    raw: "i need three, no wait, five copies of the the document",
    repaired: "I need three copies of the document.",
    changes: [{ type: "number_correction", original: "five", replacement: "three" }],
    approved: false,
    reason: "number_changed",
  },
];

export interface DemoPartialStep {
  text: string;
  delayMs: number;
}

/** Splits the raw utterance into growing partial-transcript steps. */
export function partialSteps(raw: string): DemoPartialStep[] {
  const words = raw.split(" ");
  const steps: DemoPartialStep[] = [];
  for (let i = 2; i <= words.length; i += 2) {
    steps.push({ text: words.slice(0, i).join(" "), delayMs: 220 });
  }
  if (steps.length === 0 || steps[steps.length - 1].text !== raw) {
    steps.push({ text: raw, delayMs: 220 });
  }
  return steps;
}

let cursor = 0;
export function nextDemoScript(): DemoScript {
  const script = DEMO_SCRIPTS[cursor % DEMO_SCRIPTS.length];
  cursor += 1;
  return script;
}
