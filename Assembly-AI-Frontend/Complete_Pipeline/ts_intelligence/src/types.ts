/**
 * ClearVoice 2.0 — Shared Data Contracts
 * These are frozen on "Day 1" per the task board (Section 6: Shared Contracts).
 * Person 2 CONSUMES TranscriptEvent (from Person 1) and PRODUCES RepairResult
 * (consumed by Person 3's Validator).
 */

// ---------------------------------------------------------------------------
// INPUT CONTRACT (produced by Person 1, consumed here)
// ---------------------------------------------------------------------------
export interface TranscriptEvent {
  type: "transcript.partial" | "transcript.final";
  version: 1;
  sessionId: string;
  utteranceId: string;
  text: string;
  isFinal: boolean;
  confidence?: number;
  startMs: number;
  endMs: number;
}

// ---------------------------------------------------------------------------
// P2.1 — Transcript Analyzer output
// ---------------------------------------------------------------------------
export type SegmentLabel =
  | "normal"
  | "possible_repetition"
  | "filler"
  | "restart"
  | "uncertain";

export interface TranscriptSegment {
  text: string;
  label: SegmentLabel;
  confidence: number; // 0..1 — analyzer's confidence in this label
}

export interface TranscriptAnalysis {
  segments: TranscriptSegment[];
}

// ---------------------------------------------------------------------------
// P2.2 — Conversation Context
// ---------------------------------------------------------------------------
export interface RecentUtterance {
  utteranceId: string;
  text: string;
}

export interface ConversationContext {
  recentUtterances: RecentUtterance[];
  activeEntities: string[];
  currentTopic?: string; // tracked internally, exposed for prompt-building/debugging
}

// ---------------------------------------------------------------------------
// P2.3 — User Profile
// ---------------------------------------------------------------------------
export interface RecognitionErrorMapping {
  observed: string;
  intended: string;
}

export interface UserProfile {
  preferredVocabulary: string[];
  knownEntities: string[];
  commonRecognitionErrors: RecognitionErrorMapping[];
}

// ---------------------------------------------------------------------------
// P2.4 — LLM Repair Engine output (consumed by Person 3's Validator)
// ---------------------------------------------------------------------------
export interface RepairChange {
  type: string; // e.g. "remove_repetition" | "remove_filler" | "resolve_restart" | ...
  original?: string;
  replacement?: string;
}

export interface RepairResult {
  type: "repair.completed";
  version: 1;
  sessionId: string;
  utteranceId: string;
  originalText: string;
  repairedText: string;
  confidence: number; // 0..1 — engine's confidence that the repair is safe/correct
  changes: RepairChange[];
}

// ---------------------------------------------------------------------------
// Internal: structured shape we ask the LLM to return (before we wrap it
// into a full RepairResult). Kept separate from RepairResult so a malformed
// LLM response can be caught/validated before it's trusted.
// ---------------------------------------------------------------------------
export interface LLMRepairOutputSchema {
  repairedText: string;
  confidence: number;
  changes: RepairChange[];
  uncertain: boolean; // true if the LLM itself flagged low confidence
}
