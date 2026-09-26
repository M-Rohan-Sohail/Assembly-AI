/**
 * P2.4 — LLM Repair Engine
 *
 * Checklist covered:
 *   - Design system prompt
 *   - Define input schema     (RepairInput, below)
 *   - Define output schema    (LLMRepairOutputSchema, in types.ts)
 *   - Add conversation context
 *   - Add transcript analysis
 *   - Add user profile
 *   - Add structured output
 *   - Handle malformed output
 *   - Handle timeout
 *   - Handle uncertainty
 *
 * Core LLM rules (verbatim from task board, Section 4 P2.4):
 *   1. Preserve meaning
 *   2. Make the smallest necessary changes
 *   3. Never invent facts
 *   4. Never change numbers
 *   5. Never change dates
 *   6. Never change names/entities
 *   7. Never change negation
 *   8. Preserve intentional repetition
 *   9. If uncertain -> return safer/original wording
 *
 * NOTE ON RESPONSIBILITY SPLIT:
 *   This engine tries hard to follow the 9 rules, but it is Person 3's
 *   Meaning Validator (P3.1) that is the actual safety net — per the
 *   dependency map, P3's Validator depends on RepairResult and is the
 *   last line of defense before TTS. This engine must never assume its
 *   own output is automatically trusted downstream.
 */

import {
  TranscriptEvent,
  TranscriptAnalysis,
  RepairResult,
  RepairChange,
  LLMRepairOutputSchema,
} from "./types";

const MODEL = "qwen/qwen3.8-27b";
const DEFAULT_TIMEOUT_MS = 4000; // real-time pipeline -> fail fast, fall back safe
const MAX_RETRIES_ON_MALFORMED_OUTPUT = 1;

export interface RepairInput {
  transcript: TranscriptEvent;
  analysis: TranscriptAnalysis;
  contextSummary: string; // from ConversationContextManager.buildContextSummary()
  profileSummary: string; // from UserProfileStore.buildProfileSummary()
}

export interface LLMRepairEngineOptions {
  apiKey?: string; // falls back to process.env.GROQ_API_KEY
  timeoutMs?: number;
  /**
   * Optional injection point for tests / CI (CP-8: feed 20-30 mock
   * transcripts and get structured RepairResults) so this engine can run
   * WITHOUT a live API key or network access. See tests/testPipeline.ts.
   */
  mockCompletionFn?: (input: RepairInput) => Promise<string>;
}

const SYSTEM_PROMPT = `You are the ClearVoice Repair Engine. Your ONLY job is to take a raw,
possibly disfluent speech transcript and produce a clean, natural version of
what the speaker meant to say.

You MUST follow these rules, in priority order. They are not suggestions.

1. Preserve meaning. The repaired sentence must mean exactly what the
   speaker intended.
2. Make the smallest necessary changes. Do not rewrite, rephrase, or
   "improve" style. Only remove disfluencies and resolve self-corrections.
3. Never invent facts. Do not add information that was not spoken.
4. Never change numbers. If you are not 100% sure which number the speaker
   settled on, keep the original number exactly as spoken.
5. Never change dates.
6. Never change names or entities.
7. Never change negation (never flip "not" / "don't" / "no" or remove them).
8. Preserve intentional repetition. Repeated words used for emphasis
   ("no, no, I really mean it", "very very good") are NOT dysfluencies —
   keep them as-is.
9. If you are uncertain about ANY correction, do not guess. Return the
   safer, more literal wording (closer to the original) and set
   "uncertain": true.

You will be given:
- The raw transcript text
- A structured dysfluency analysis (segments labeled: normal,
  possible_repetition, filler, restart, uncertain)
- Recent conversation context
- The user's profile (preferred vocabulary, known entities, known STT
  recognition errors)

Typical fixes you SHOULD make:
- Remove stutters/false starts: "I I wanted" -> "I wanted"
- Remove filler words: "um", "uh", "like" (when used as filler, not verb)
- Resolve self-corrections, keeping only the FINAL stated value:
  "Friday... no Wednesday" -> "Wednesday"
- Remove restart fragments that were abandoned: "I want Friday—actually
  Thursday" -> "I want Thursday"

Typical things you must NOT do:
- Do not delete a repetition that is emphatic/intentional (rule 8)
- Do not "correct" a number, date, or name based on assumption (rules 4-6)
- Do not remove or flip a negation (rule 7)
- Do not fill in missing information the speaker never said (rule 3)

OUTPUT FORMAT — respond with ONLY a single JSON object, no prose, no
markdown code fences, matching exactly this shape:
{
  "repairedText": string,
  "confidence": number between 0 and 1,
  "changes": [
    { "type": string, "original": string (optional), "replacement": string (optional) }
  ],
  "uncertain": boolean
}`;

function buildUserPrompt(input: RepairInput): string {
  const { transcript, analysis, contextSummary, profileSummary } = input;

  const analysisLines = analysis.segments
    .map((s) => `  - "${s.text}" [${s.label}, confidence=${s.confidence}]`)
    .join("\n");

  return `RAW TRANSCRIPT:
"${transcript.text}"

DYSFLUENCY ANALYSIS:
${analysisLines || "  (no segments)"}

CONVERSATION CONTEXT:
${contextSummary}

USER PROFILE:
${profileSummary}

Produce the JSON repair output now.`;
}

/** Strips accidental markdown code fences some models add despite instructions. */
function stripCodeFences(raw: string): string {
  return raw
    .trim()
    .replace(/^```(json)?/i, "")
    .replace(/```$/i, "")
    .trim();
}

function isValidSchema(obj: any): obj is LLMRepairOutputSchema {
  return (
    obj &&
    typeof obj.repairedText === "string" &&
    typeof obj.confidence === "number" &&
    obj.confidence >= 0 &&
    obj.confidence <= 1 &&
    Array.isArray(obj.changes) &&
    obj.changes.every(
      (c: any) =>
        c &&
        typeof c.type === "string" &&
        (c.original === undefined || typeof c.original === "string") &&
        (c.replacement === undefined || typeof c.replacement === "string")
    ) &&
    typeof obj.uncertain === "boolean"
  );
}

function withTimeout<T>(promise: Promise<T>, ms: number, label: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new Error(`${label} timed out after ${ms}ms`)),
      ms
    );
    promise
      .then((result) => {
        clearTimeout(timer);
        resolve(result);
      })
      .catch((err) => {
        clearTimeout(timer);
        reject(err);
      });
  });
}

/** Deterministic, hard safety net that runs BEFORE we ever trust the LLM's
 *  own "confidence" claim. Even a well-formed, high-confidence LLM response
 *  gets rejected here if it violates a hard rule (number/date changed etc.)
 *  by naive heuristics. This is intentionally conservative — Person 3's
 *  Validator (P3.1) is the real, authoritative check downstream, but Person
 *  2 should not hand off obviously-broken repairs.
 */
function violatesHardRules(originalText: string, repairedText: string): boolean {
  const extractNumbers = (t: string): string[] => t.match(/\d+([.,]\d+)?/g) ?? [];
  const origNums = extractNumbers(originalText);
  const repNums = extractNumbers(repairedText);
  // If repaired text contains a number that never appeared in the original
  // at all, that's a strong signal of an invented/changed number.
  for (const n of repNums) {
    if (!origNums.includes(n)) return true;
  }
  return false;
}

function fallbackResult(
  transcript: TranscriptEvent,
  reason: string
): RepairResult {
  return {
    type: "repair.completed",
    version: 1,
    sessionId: transcript.sessionId,
    utteranceId: transcript.utteranceId,
    originalText: transcript.text,
    repairedText: transcript.text, // Rule 9: uncertain -> return original
    confidence: 0,
    changes: [{ type: `fallback_no_change:${reason}` }],
  };
}

export class LLMRepairEngine {
  private apiKey: string | null;
  private timeoutMs: number;
  private mockCompletionFn?: (input: RepairInput) => Promise<string>;

  constructor(options: LLMRepairEngineOptions = {}) {
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.mockCompletionFn = options.mockCompletionFn;

    this.apiKey = options.apiKey ?? process.env.GROQ_API_KEY ?? null;
  }

  private async getRawCompletion(input: RepairInput): Promise<string> {
    if (this.mockCompletionFn) {
      return this.mockCompletionFn(input);
    }
    if (!this.apiKey) {
      throw new Error(
        "No GROQ_API_KEY configured and no mockCompletionFn provided."
      );
    }

    const response = await fetch("https://api.groq.com/openai/v1/chat/completions", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${this.apiKey}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        model: MODEL,
        max_tokens: 1000,
        messages: [
          { role: "system", content: SYSTEM_PROMPT },
          { role: "user", content: buildUserPrompt(input) }
        ],
        response_format: { type: "json_object" }
      })
    });

    if (!response.ok) {
      const err = await response.text();
      throw new Error(`Groq API error: ${response.status} ${err}`);
    }

    const data = await response.json() as any;
    if (!data.choices || !data.choices[0] || !data.choices[0].message || !data.choices[0].message.content) {
      throw new Error("LLM response contained no text block.");
    }
    return data.choices[0].message.content;
  }

  /**
   * Runs one repair attempt end-to-end: call LLM -> parse -> validate
   * schema -> validate hard rules -> build RepairResult.
   * Handles: timeout, malformed JSON, schema mismatch, hard-rule
   * violations, and explicit LLM-flagged uncertainty — all fall back to
   * "return the original text unchanged" (Rule 9), never throwing past
   * the caller.
   */
  async repair(input: RepairInput): Promise<RepairResult> {
    const { transcript } = input;

    let attempt = 0;
    let lastError: string = "unknown";

    while (attempt <= MAX_RETRIES_ON_MALFORMED_OUTPUT) {
      attempt++;
      try {
        const raw = await withTimeout(
          this.getRawCompletion(input),
          this.timeoutMs,
          "LLM repair call"
        );

        const cleaned = stripCodeFences(raw);
        let parsed: any;
        try {
          parsed = JSON.parse(cleaned);
        } catch {
          lastError = "malformed_json";
          continue; // retry once
        }

        if (!isValidSchema(parsed)) {
          lastError = "schema_mismatch";
          continue; // retry once
        }

        const schema = parsed as LLMRepairOutputSchema;

        // Rule 9: LLM itself flagged uncertainty -> return original.
        if (schema.uncertain) {
          return fallbackResult(transcript, "llm_flagged_uncertain");
        }

        // Low-confidence numeric threshold -> treat as uncertain too.
        if (schema.confidence < 0.5) {
          return fallbackResult(transcript, "low_confidence");
        }

        // Hard-rule guard (numbers must not be invented/changed).
        if (violatesHardRules(transcript.text, schema.repairedText)) {
          return fallbackResult(transcript, "hard_rule_violation_numbers");
        }

        return this.toRepairResult(transcript, schema);
      } catch (err: any) {
        lastError = err?.message ?? "unknown_error";
        if (String(lastError).includes("timed out")) {
          // Don't burn the retry budget on a timeout — fail safe immediately.
          return fallbackResult(transcript, "timeout");
        }
        // Non-timeout error (e.g. network/API error) — retry once, then fail safe.
      }
    }

    return fallbackResult(transcript, lastError);
  }

  private toRepairResult(
    transcript: TranscriptEvent,
    schema: LLMRepairOutputSchema
  ): RepairResult {
    const changes: RepairChange[] = schema.changes.map((c) => ({
      type: c.type,
      original: c.original,
      replacement: c.replacement,
    }));

    return {
      type: "repair.completed",
      version: 1,
      sessionId: transcript.sessionId,
      utteranceId: transcript.utteranceId,
      originalText: transcript.text,
      repairedText: schema.repairedText,
      confidence: schema.confidence,
      changes,
    };
  }
}
