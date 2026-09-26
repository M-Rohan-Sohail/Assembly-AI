/**
 * P2.1 — Transcript Analyzer
 *
 * Detects (per task board):
 *   - Repeated words
 *   - Repeated fragments
 *   - Fillers
 *   - Restarts
 *   - Incomplete phrases
 *   - Low-confidence regions
 *   - Potential STT errors
 *
 * IMPORTANT (explicit rule from task board):
 *   Do NOT automatically flag every repetition as an error to remove.
 *   "I really, really like this." is likely INTENTIONAL emphasis, not a
 *   dysfluency. This analyzer marks it "possible_repetition" (not "filler"
 *   or auto-deleted) precisely so the LLM Repair stage — which has full
 *   sentence context — makes the final call, per Rule 8: "Preserve
 *   intentional repetition."
 *
 * This is a fast, deterministic, rule-based pass. It intentionally does NOT
 * call an LLM — it exists to give the LLM Repair Engine cheap, structured
 * signal, and to work standalone (CP-5 requires it to pass on 10-20 curated
 * examples with no external dependency).
 */

import { TranscriptAnalysis, TranscriptSegment, SegmentLabel } from "./types";

// Common English filler words / disfluency markers.
const FILLER_WORDS = new Set([
  "um",
  "umm",
  "uh",
  "uhh",
  "erm",
  "er",
  "ah",
  "like",
  "you know",
  "i mean",
  "so yeah",
  "kind of",
  "sort of",
]);

// Words that, when immediately followed by a correction, strongly signal a
// restart ("no", "actually", "sorry", "wait", "I mean").
const RESTART_MARKERS = new Set([
  "no",
  "actually",
  "sorry",
  "wait",
  "scratch that",
  "i mean",
  "rather",
]);

// Words that, when repeated back-to-back with emotional/emphatic framing
// nearby, tend to be INTENTIONAL emphasis rather than dysfluency.
// e.g. "no, no, I really mean it" / "very very good"
const EMPHASIS_CONTEXT = new Set([
  "really",
  "very",
  "so",
  "please",
  "no",
  "yes",
]);

interface Token {
  raw: string;
  clean: string; // lowercased, punctuation-stripped
  index: number;
}

function tokenize(text: string): Token[] {
  // Insert spacing around em/en-dashes so a self-interruption like
  // "Friday—actually" splits into separate tokens ("Friday—", "actually")
  // instead of being treated as one unrecognized word.
  const spaced = text.replace(/([—–])/g, " $1 ");
  const rawTokens = spaced.split(/\s+/).filter(Boolean);
  return rawTokens.map((raw, index) => ({
    raw,
    clean: raw.toLowerCase().replace(/[.,!?;:"'—–-]/g, ""),
    index,
  }));
}

/**
 * Groups consecutive tokens that share the same label into a single
 * segment, joined by the original whitespace-preserving raw text.
 */
function collapseIntoSegments(
  tokens: Token[],
  labels: SegmentLabel[],
  confidences: number[]
): TranscriptSegment[] {
  const segments: TranscriptSegment[] = [];
  let i = 0;
  while (i < tokens.length) {
    const label = labels[i];
    let j = i;
    let confSum = 0;
    const words: string[] = [];
    while (j < tokens.length && labels[j] === label) {
      words.push(tokens[j].raw);
      confSum += confidences[j];
      j++;
    }
    segments.push({
      text: words.join(" "),
      label,
      confidence: Number((confSum / (j - i)).toFixed(2)),
    });
    i = j;
  }
  return segments;
}

/**
 * Detects immediate word-level repetition: "I I wanted" -> tokens[0]="i",
 * tokens[1]="i". Also detects short repeated fragments like
 * "book an appointment book an appointment" (2-4 word phrase repeated
 * back-to-back).
 */
function detectRepetitions(tokens: Token[]): boolean[] {
  const flagged = new Array(tokens.length).fill(false);

  // Single-word immediate repetition (allow up to 3 in a row: "I I I want")
  for (let i = 1; i < tokens.length; i++) {
    if (tokens[i].clean && tokens[i].clean === tokens[i - 1].clean) {
      flagged[i - 1] = true;
      flagged[i] = true;
    }
  }

  // Repeated multi-word fragments (phrase length 2..4)
  for (let phraseLen = 2; phraseLen <= 4; phraseLen++) {
    for (let i = 0; i + phraseLen * 2 <= tokens.length; i++) {
      const a = tokens
        .slice(i, i + phraseLen)
        .map((t) => t.clean)
        .join(" ");
      const b = tokens
        .slice(i + phraseLen, i + phraseLen * 2)
        .map((t) => t.clean)
        .join(" ");
      if (a && a === b) {
        for (let k = i; k < i + phraseLen * 2; k++) flagged[k] = true;
      }
    }
  }

  return flagged;
}

/**
 * Decides whether a flagged repetition looks INTENTIONAL (emphasis) rather
 * than a dysfluency, based on nearby emphasis-context words or comma-joined
 * repetition ("no, no, ...").
 */
function looksIntentional(tokens: Token[], idx: number): boolean {
  const windowStart = Math.max(0, idx - 2);
  const windowEnd = Math.min(tokens.length, idx + 3);
  for (let k = windowStart; k < windowEnd; k++) {
    if (EMPHASIS_CONTEXT.has(tokens[k].clean)) return true;
  }
  // Comma between the repeated words is a strong "intentional" signal:
  // "really, really" vs "really really"
  if (idx > 0 && tokens[idx - 1].raw.includes(",")) return true;
  return false;
}

function detectFillers(tokens: Token[]): boolean[] {
  return tokens.map((t) => FILLER_WORDS.has(t.clean));
}

function detectRestartMarkers(tokens: Token[]): boolean[] {
  return tokens.map((t) => RESTART_MARKERS.has(t.clean));
}

/** Flags a trailing incomplete clause, e.g. text ending in "I wanted to…" */
function endsIncomplete(text: string): boolean {
  const trimmed = text.trim();
  if (!trimmed) return false;
  if (trimmed.endsWith("…") || trimmed.endsWith("...")) return true;
  // Ends with a dash (self-interruption): "Friday—" / "Friday-"
  if (/[-—]\s*$/.test(trimmed)) return true;
  // Ends with a dangling function word (to/for/and/but/the/a/an/of/with/that)
  const dangling = new Set([
    "to",
    "for",
    "and",
    "but",
    "the",
    "a",
    "an",
    "of",
    "with",
    "that",
    "in",
    "on",
  ]);
  const lastWord = trimmed
    .split(/\s+/)
    .pop()!
    .toLowerCase()
    .replace(/[.,!?;:"']/g, "");
  return dangling.has(lastWord);
}

export function analyzeTranscript(
  text: string,
  confidence?: number
): TranscriptAnalysis {
  const tokens = tokenize(text);
  if (tokens.length === 0) {
    return { segments: [] };
  }

  const repetitionFlags = detectRepetitions(tokens);
  const fillerFlags = detectFillers(tokens);
  const restartFlags = detectRestartMarkers(tokens);
  const baseConfidence = confidence ?? 1.0;

  const labels: SegmentLabel[] = tokens.map((t, i) => {
    if (fillerFlags[i]) return "filler";
    if (repetitionFlags[i]) {
      return looksIntentional(tokens, i) ? "normal" : "possible_repetition";
    }
    if (restartFlags[i]) return "restart";
    // Low-confidence STT region -> flag as uncertain regardless of content
    if (baseConfidence < 0.55) return "uncertain";
    return "normal";
  });

  const confidences: number[] = tokens.map((t, i) => {
    if (labels[i] === "possible_repetition") return 0.85;
    if (labels[i] === "filler") return 0.9;
    if (labels[i] === "restart") return 0.75;
    if (labels[i] === "uncertain") return Math.max(0.3, baseConfidence);
    return baseConfidence;
  });

  const segments = collapseIntoSegments(tokens, labels, confidences);

  // If the utterance trails off incomplete, mark the FINAL segment as
  // "uncertain" too (it's an incomplete phrase) — merge if already uncertain.
  if (endsIncomplete(text) && segments.length > 0) {
    const last = segments[segments.length - 1];
    if (last.label === "normal") {
      last.label = "uncertain";
      last.confidence = Math.min(last.confidence, 0.5);
    }
  }

  return { segments };
}
