/**
 * Person2Pipeline — glues together everything Person 2 owns:
 *   TranscriptEvent -> [Analyzer] -> [Context] -> [Profile] -> [LLM Repair]
 *   -> RepairResult
 *
 * This is what Person 3's Orchestrator (P3.4) calls:
 *   const repair = await intelligence.repair(event);
 * (matches the exact example in the task board's P3.4 section)
 */

import { TranscriptEvent, RepairResult } from "./types";
import { analyzeTranscript } from "./analyzer";
import { ConversationContextManager } from "./context";
import { UserProfileStore } from "./userProfile";
import { LLMRepairEngine, LLMRepairEngineOptions } from "./llmRepair";

export interface Person2PipelineOptions {
  llmOptions?: LLMRepairEngineOptions;
}

export class Person2Pipeline {
  readonly contextManager: ConversationContextManager;
  readonly profileStore: UserProfileStore;
  private readonly llmEngine: LLMRepairEngine;

  constructor(options: Person2PipelineOptions = {}) {
    this.contextManager = new ConversationContextManager();
    this.profileStore = new UserProfileStore();
    this.llmEngine = new LLMRepairEngine(options.llmOptions);
  }

  /**
   * Full repair pipeline for a single finalized transcript.
   * userId defaults to sessionId when no separate user identity is wired up
   * yet (fine for MVP — swap in real auth/user IDs later without touching
   * this method's shape).
   */
  async repair(event: TranscriptEvent, userId?: string): Promise<RepairResult> {
    const uid = userId ?? event.sessionId;

    // 1. Apply known STT recognition-error corrections BEFORE analysis/LLM
    //    (cheap, deterministic, no LLM code changes needed — CP-7).
    const correctedText = this.profileStore.applyKnownCorrections(
      uid,
      event.text
    );
    const workingEvent: TranscriptEvent = { ...event, text: correctedText };

    // 2. Dysfluency analysis (P2.1)
    const analysis = analyzeTranscript(workingEvent.text, workingEvent.confidence);

    // 3. Build context + profile summaries (P2.2 / P2.3)
    const contextSummary = this.contextManager.buildContextSummary(
      workingEvent.sessionId
    );
    const profileSummary = this.profileStore.buildProfileSummary(uid);

    // 4. LLM repair (P2.4)
    const result = await this.llmEngine.repair({
      transcript: workingEvent,
      analysis,
      contextSummary,
      profileSummary,
    });

    // 5. Update rolling context with the utterance (store repaired text so
    //    future turns get clean context, per "understanding" the point of
    //    ConversationContext existing at all).
    this.contextManager.addUtterance(
      workingEvent.sessionId,
      workingEvent.utteranceId,
      result.repairedText
    );

    return result;
  }
}
