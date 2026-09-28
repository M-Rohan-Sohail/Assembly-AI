/**
 * P2.3 — User Profile
 *
 * Checklist covered:
 *   - Define profile schema           (see types.ts -> UserProfile)
 *   - Store preferred vocabulary
 *   - Store known entities
 *   - Store recurring recognition errors
 *   - Inject profile into LLM context
 *
 * Kept deliberately simple per the task board note: "Keep this simple for
 * the 2-week MVP." No persistence layer is implied here — bring your own
 * (DB/session store); this class is the in-memory contract + prompt
 * injection logic, storage-agnostic so swapping in Postgres/Redis later
 * doesn't touch the LLM Repair Engine at all (CP-7: a known vocabulary item
 * can influence processing WITHOUT changing core LLM code).
 */

import { UserProfile, RecognitionErrorMapping } from "./types";

function emptyProfile(): UserProfile {
  return {
    preferredVocabulary: [],
    knownEntities: [],
    commonRecognitionErrors: [],
  };
}

export class UserProfileStore {
  private profiles: Map<string, UserProfile> = new Map();

  /** Retrieve a user's profile, creating an empty one if it doesn't exist. */
  getProfile(userId: string): UserProfile {
    if (!this.profiles.has(userId)) {
      this.profiles.set(userId, emptyProfile());
    }
    return this.profiles.get(userId)!;
  }

  setProfile(userId: string, profile: UserProfile): void {
    this.profiles.set(userId, profile);
  }

  addPreferredVocabulary(userId: string, word: string): void {
    const p = this.getProfile(userId);
    if (!p.preferredVocabulary.includes(word)) {
      p.preferredVocabulary.push(word);
    }
  }

  addKnownEntity(userId: string, entity: string): void {
    const p = this.getProfile(userId);
    if (!p.knownEntities.includes(entity)) {
      p.knownEntities.push(entity);
    }
  }

  /**
   * Records that the STT/pipeline has previously heard `observed` when the
   * user actually meant `intended` (e.g. STT keeps hearing "Sean" but the
   * user always means "Xian"). Deduplicates on the observed->intended pair.
   */
  addRecognitionError(userId: string, mapping: RecognitionErrorMapping): void {
    const p = this.getProfile(userId);
    const exists = p.commonRecognitionErrors.some(
      (e) => e.observed === mapping.observed && e.intended === mapping.intended
    );
    if (!exists) p.commonRecognitionErrors.push(mapping);
  }

  /**
   * Applies known observed->intended recognition-error corrections directly
   * to a raw transcript BEFORE it reaches the LLM. This is a cheap,
   * deterministic pre-pass — it does not require any LLM code changes,
   * satisfying CP-7.
   */
  applyKnownCorrections(userId: string, text: string): string {
    const p = this.getProfile(userId);
    let corrected = text;
    for (const { observed, intended } of p.commonRecognitionErrors) {
      const pattern = new RegExp(`\\b${escapeRegExp(observed)}\\b`, "gi");
      corrected = corrected.replace(pattern, intended);
    }
    return corrected;
  }

  /**
   * Renders the profile as a compact block for injection into the LLM
   * system/user prompt. Empty profile -> minimal "no profile" line, so we
   * don't waste prompt tokens on new users.
   */
  buildProfileSummary(userId: string): string {
    const p = this.getProfile(userId);
    const hasAnything =
      p.preferredVocabulary.length > 0 ||
      p.knownEntities.length > 0 ||
      p.commonRecognitionErrors.length > 0;

    if (!hasAnything) return "No user profile data available.";

    const parts: string[] = [];
    if (p.preferredVocabulary.length > 0) {
      parts.push(`Preferred vocabulary: ${p.preferredVocabulary.join(", ")}`);
    }
    if (p.knownEntities.length > 0) {
      parts.push(`Known entities (names/places the user uses): ${p.knownEntities.join(", ")}`);
    }
    if (p.commonRecognitionErrors.length > 0) {
      const mappings = p.commonRecognitionErrors
        .map((e) => `"${e.observed}" usually means "${e.intended}"`)
        .join("; ");
      parts.push(`Known STT recognition errors: ${mappings}`);
    }
    return parts.join("\n");
  }
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
