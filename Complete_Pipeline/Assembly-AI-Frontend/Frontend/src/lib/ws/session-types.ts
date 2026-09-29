import type { PipelineStage, ValidationReason } from "./types";

export type ConnectionStatus = "offline" | "connecting" | "online" | "demo";

export interface UtteranceRecord {
  utteranceId: string;
  rawText: string;
  repairedText: string;
  isFinal: boolean;
  approved: boolean | null;
  reason: ValidationReason | null;
  source: "repaired" | "safer" | "original" | null;
  startedAt: number;
  updatedAt: number;
}

export interface SessionState {
  connection: ConnectionStatus;
  stage: PipelineStage;
  sessionId: string | null;
  current: UtteranceRecord | null;
  history: UtteranceRecord[];
  isSpeaking: boolean;
  isMuted: boolean;
  error: string | null;
}

export const MAX_HISTORY = 25;

export function emptyUtterance(utteranceId: string): UtteranceRecord {
  const now = Date.now();
  return {
    utteranceId,
    rawText: "",
    repairedText: "",
    isFinal: false,
    approved: null,
    reason: null,
    source: null,
    startedAt: now,
    updatedAt: now,
  };
}

export const initialSessionState: SessionState = {
  connection: "offline",
  stage: "idle",
  sessionId: null,
  current: null,
  history: [],
  isSpeaking: false,
  isMuted: false,
  error: null,
};
