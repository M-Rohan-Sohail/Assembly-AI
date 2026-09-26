/**
 * ClearVoice 2.0 — Person 2: Intelligence / LLM
 * Public exports for consumption by Person 3's Orchestrator (or anyone
 * integrating this module).
 */

export * from "./types";
export { analyzeTranscript } from "./analyzer";
export { ConversationContextManager } from "./context";
export { UserProfileStore } from "./userProfile";
export { LLMRepairEngine } from "./llmRepair";
export type { RepairInput, LLMRepairEngineOptions } from "./llmRepair";
export { Person2Pipeline } from "./pipeline";
export type { Person2PipelineOptions } from "./pipeline";
