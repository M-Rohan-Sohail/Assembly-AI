/**
 * Wire contract between this frontend and the Python orchestrator's
 * WebSocket endpoint (Phase 0 of the frontend plan — not built yet on the
 * backend as of this writing). Field names/shapes mirror
 * python_core/src/contracts.py 1:1 so the backend side is a thin JSON
 * serialization of the existing TypedDicts (bytes fields become base64
 * strings over the wire).
 */

export type PipelineStage =
  | "idle"
  | "listening"
  | "repairing"
  | "validating"
  | "speaking";

// ---- client -> server -------------------------------------------------

export interface SessionStartMessage {
  type: "session.start";
  session_id: string;
  sample_rate: number;
  channels: number;
}

export interface SessionStopMessage {
  type: "session.stop";
  session_id: string;
}

export interface SessionMuteMessage {
  type: "session.mute";
  session_id: string;
  muted: boolean;
}

/** Barge-in: stop whatever is currently being spoken; session stays open. */
export interface PlaybackCancelMessage {
  type: "playback.cancel";
  session_id: string;
}

/** Mirrors contracts.AudioChunk, with payload base64-encoded for JSON transport. */
export interface AudioInputMessage {
  type: "audio.chunk";
  session_id: string;
  sequence: number;
  timestamp_ms: number;
  payload_b64: string;
  sample_rate: number;
  channels: number;
}

export type ClientMessage =
  | SessionStartMessage
  | SessionStopMessage
  | SessionMuteMessage
  | PlaybackCancelMessage
  | AudioInputMessage;

// ---- server -> client ---------------------------------------------------

/** Mirrors contracts.TranscriptEvent. */
export interface TranscriptServerEvent {
  type: "transcript.partial" | "transcript.final";
  version: number;
  session_id: string;
  utterance_id: string;
  text: string;
  is_final: boolean;
  confidence: number | null;
  start_ms: number;
  end_ms: number;
}

/** Mirrors contracts.RepairResult. */
export interface RepairChange {
  type?: string;
  original?: string;
  replacement?: string;
}

export interface RepairServerEvent {
  type: "repair.completed";
  version: number;
  session_id: string;
  utterance_id: string;
  original_text: string;
  repaired_text: string;
  confidence: number;
  changes: RepairChange[];
}

/** Mirrors contracts.ValidationReason values. */
export type ValidationReason =
  | "approved"
  | "number_changed"
  | "date_changed"
  | "entity_changed"
  | "negation_changed"
  | "semantic_risk"
  | "invalid_output";

/**
 * Not a literal contracts.py TypedDict (the orchestrator keeps this
 * internal as UtteranceResult), but this is the shape it needs to expose
 * to a client: whether the repair was approved, why, and which text
 * source was ultimately spoken (repaired / safer / original fallback).
 */
export interface ValidationServerEvent {
  type: "validation.result";
  session_id: string;
  utterance_id: string;
  approved: boolean;
  reason: ValidationReason;
  source: "repaired" | "safer" | "original";
  spoken_text: string;
}

/** Mirrors contracts.AudioOutputEvent, with audio_chunk base64-encoded. */
export interface AudioOutputServerEvent {
  type: "audio.chunk" | "audio.final";
  version: number;
  session_id: string;
  utterance_id: string;
  sequence: number;
  audio_chunk_b64: string;
  is_final: boolean;
}

export interface StageServerEvent {
  type: "stage.update";
  session_id: string;
  utterance_id: string | null;
  stage: PipelineStage;
}

export interface ErrorServerEvent {
  type: "pipeline.error";
  session_id: string;
  utterance_id: string | null;
  stage: "repair" | "fallback" | "tts" | "playback";
  message: string;
}

export type ServerEvent =
  | TranscriptServerEvent
  | RepairServerEvent
  | ValidationServerEvent
  | AudioOutputServerEvent
  | StageServerEvent
  | ErrorServerEvent;
