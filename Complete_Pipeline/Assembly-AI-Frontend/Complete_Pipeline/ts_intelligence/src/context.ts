/**
 * P2.2 — Conversation Context
 *
 * Checklist covered:
 *   - Store recent utterances
 *   - Limit context size
 *   - Track current topic
 *   - Track relevant entities
 *   - Clear context between sessions
 *   - Prevent unlimited memory growth
 *
 * Design notes:
 *   One ConversationContextManager instance is process-wide; it keeps a
 *   Map<sessionId, ConversationContext> so multiple concurrent sessions
 *   never bleed context into each other. Each session's history is capped
 *   (ring-buffer style) so memory cannot grow unbounded over a long call.
 */

import { ConversationContext, RecentUtterance } from "./types";

const DEFAULT_MAX_RECENT_UTTERANCES = 6;
const DEFAULT_MAX_ENTITIES = 25;

// Very small stopword list used only to avoid tagging common function words
// as "entities" when doing naive capitalized-word / number extraction.
const STOPWORDS = new Set([
  "i",
  "the",
  "a",
  "an",
  "to",
  "for",
  "on",
  "in",
  "at",
  "and",
  "but",
  "or",
  "is",
  "am",
  "are",
  "was",
  "were",
  "it",
  "this",
  "that",
]);

interface ContextManagerOptions {
  maxRecentUtterances?: number;
  maxEntities?: number;
}

/** Naive entity extraction: capitalized words and weekday/date-like tokens. */
function extractCandidateEntities(text: string): string[] {
  const found = new Set<string>();
  const weekdays = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
  ];
  const words = text.split(/\s+/);
  for (const raw of words) {
    const clean = raw.replace(/[.,!?;:"']/g, "");
    if (!clean) continue;
    const lower = clean.toLowerCase();
    if (weekdays.includes(lower)) {
      found.add(clean[0].toUpperCase() + clean.slice(1).toLowerCase());
      continue;
    }
    // Capitalized word, not at index 0 stopword-only check, and not a
    // common stopword.
    if (/^[A-Z][a-zA-Z]*$/.test(clean) && !STOPWORDS.has(lower)) {
      found.add(clean);
    }
  }
  return Array.from(found);
}

/** Extremely lightweight topic heuristic: pick the most salient noun-ish
 *  token from the most recent utterance. This is intentionally simple —
 *  it exists to give the LLM a cheap hint, not to be a real topic model.
 */
function inferTopic(recentText: string): string | undefined {
  const topicKeywords: Record<string, string[]> = {
    scheduling: ["meeting", "appointment", "schedule", "calendar", "book"],
    billing: ["invoice", "payment", "bill", "charge", "refund"],
    travel: ["flight", "ticket", "trip", "hotel", "booking"],
    support: ["issue", "problem", "broken", "error", "help"],
  };
  const lower = recentText.toLowerCase();
  for (const [topic, keywords] of Object.entries(topicKeywords)) {
    if (keywords.some((k) => lower.includes(k))) return topic;
  }
  return undefined;
}

export class ConversationContextManager {
  private sessions: Map<string, ConversationContext> = new Map();
  private readonly maxRecentUtterances: number;
  private readonly maxEntities: number;

  constructor(options: ContextManagerOptions = {}) {
    this.maxRecentUtterances =
      options.maxRecentUtterances ?? DEFAULT_MAX_RECENT_UTTERANCES;
    this.maxEntities = options.maxEntities ?? DEFAULT_MAX_ENTITIES;
  }

  /** Retrieve current context for a session (creates an empty one if new). */
  getContext(sessionId: string): ConversationContext {
    if (!this.sessions.has(sessionId)) {
      this.sessions.set(sessionId, {
        recentUtterances: [],
        activeEntities: [],
        currentTopic: undefined,
      });
    }
    return this.sessions.get(sessionId)!;
  }

  /**
   * Adds a finalized utterance to the session's rolling context.
   * Should be called AFTER repair (so context reflects clean text) or
   * BEFORE, depending on integration choice — this module stores whatever
   * text it is given, so Person 3's Orchestrator / Person 2's own pipeline
   * decides which text (original vs repaired) to feed forward.
   */
  addUtterance(sessionId: string, utteranceId: string, text: string): void {
    const ctx = this.getContext(sessionId);

    const entry: RecentUtterance = { utteranceId, text };
    ctx.recentUtterances.push(entry);

    // Ring-buffer cap — prevents unlimited memory growth over long calls.
    if (ctx.recentUtterances.length > this.maxRecentUtterances) {
      ctx.recentUtterances.splice(
        0,
        ctx.recentUtterances.length - this.maxRecentUtterances
      );
    }

    // Update entities (dedup, cap size, most-recent entities kept)
    const newEntities = extractCandidateEntities(text);
    const merged = Array.from(
      new Set([...ctx.activeEntities, ...newEntities])
    );
    ctx.activeEntities =
      merged.length > this.maxEntities
        ? merged.slice(merged.length - this.maxEntities)
        : merged;

    // Update topic hint from the most recent utterance
    const inferred = inferTopic(text);
    if (inferred) ctx.currentTopic = inferred;
  }

  /** Clears context for a single session (e.g. on session end/disconnect). */
  clearSession(sessionId: string): void {
    this.sessions.delete(sessionId);
  }

  /** Clears ALL sessions — use with care (e.g. full service restart). */
  clearAll(): void {
    this.sessions.clear();
  }

  /**
   * Builds a compact, LLM-friendly context string. Kept short on purpose:
   * the LLM Repair prompt should stay small and fast (this is a
   * low-latency, real-time pipeline).
   */
  buildContextSummary(sessionId: string): string {
    const ctx = this.getContext(sessionId);
    if (ctx.recentUtterances.length === 0) return "No prior context.";

    const lines = ctx.recentUtterances
      .slice(-3) // last 3 utterances is enough signal, keeps prompt tight
      .map((u) => `- "${u.text}"`)
      .join("\n");

    const entities =
      ctx.activeEntities.length > 0
        ? ctx.activeEntities.join(", ")
        : "none observed";

    const topic = ctx.currentTopic ?? "unknown";

    return [
      `Recent utterances:\n${lines}`,
      `Active entities: ${entities}`,
      `Current topic: ${topic}`,
    ].join("\n");
  }
}
