"use client";

import { useCallback, useReducer, useRef } from "react";
import { makeSessionId } from "@/lib/utils";
import { DEMO_SCRIPTS, nextDemoScript, partialSteps } from "./demo-simulation";
import type { AudioChunkPayload } from "@/lib/audio/useMicCapture";
import {
  emptyUtterance,
  initialSessionState,
  MAX_HISTORY,
  type ConnectionStatus,
  type SessionState,
  type UtteranceRecord,
} from "./session-types";
import type { ClientMessage, PipelineStage, ServerEvent } from "./types";

type Action =
  | { kind: "connection"; status: ConnectionStatus }
  | { kind: "session-start"; sessionId: string }
  | { kind: "session-stop" }
  | { kind: "mute"; muted: boolean }
  | { kind: "clear-history" }
  | { kind: "stage"; stage: PipelineStage }
  | { kind: "server-event"; event: ServerEvent }
  | { kind: "error"; message: string | null };

function upsertCurrent(state: SessionState, utteranceId: string): UtteranceRecord {
  if (state.current && state.current.utteranceId === utteranceId) return state.current;
  return emptyUtterance(utteranceId);
}

function reducer(state: SessionState, action: Action): SessionState {
  switch (action.kind) {
    case "connection":
      return { ...state, connection: action.status };
    case "session-start":
      return { ...initialSessionState, connection: state.connection, sessionId: action.sessionId, stage: "listening" };
    case "session-stop":
      return { ...state, stage: "idle", sessionId: null, current: null };
    case "mute":
      return { ...state, isMuted: action.muted };
    case "clear-history":
      return { ...state, history: [] };
    case "stage":
      return { ...state, stage: action.stage };
    case "error":
      return { ...state, error: action.message };
    case "server-event": {
      const event = action.event;
      switch (event.type) {
        case "transcript.partial":
        case "transcript.final": {
          const current = upsertCurrent(state, event.utterance_id);
          const updated: UtteranceRecord = {
            ...current,
            rawText: event.text,
            isFinal: event.is_final,
            updatedAt: Date.now(),
          };
          return { ...state, current: updated };
        }
        case "repair.completed": {
          if (!state.current || state.current.utteranceId !== event.utterance_id) return state;
          return {
            ...state,
            current: { ...state.current, repairedText: event.repaired_text, updatedAt: Date.now() },
          };
        }
        case "validation.result": {
          if (!state.current || state.current.utteranceId !== event.utterance_id) return state;
          const finalized: UtteranceRecord = {
            ...state.current,
            repairedText: event.spoken_text,
            approved: event.approved,
            reason: event.reason,
            source: event.source,
            updatedAt: Date.now(),
          };
          const history = [finalized, ...state.history].slice(0, MAX_HISTORY);
          return { ...state, current: finalized, history };
        }
        case "stage.update":
          return { ...state, stage: event.stage };
        case "pipeline.error":
          return { ...state, error: `${event.stage}: ${event.message}` };
        default:
          return state;
      }
    }
    default:
      return state;
  }
}

export interface UseClearVoiceSessionOptions {
  wsUrl?: string;
  useDemoMode: boolean;
  onAudioOutputChunk?: (audioChunkB64: string, isFinal: boolean) => void;
  onDemoSpeak?: (text: string) => Promise<void>;
}

export function useClearVoiceSession(options: UseClearVoiceSessionOptions) {
  const { wsUrl, useDemoMode, onAudioOutputChunk, onDemoSpeak } = options;
  const [state, dispatch] = useReducer(reducer, initialSessionState);
  const wsRef = useRef<WebSocket | null>(null);
  const demoCancelRef = useRef(false);
  const sessionIdRef = useRef<string | null>(null);
  const isMutedRef = useRef(false);

  const sendAudioChunk = useCallback((chunk: AudioChunkPayload) => {
    const ws = wsRef.current;
    const sessionId = sessionIdRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN || !sessionId || isMutedRef.current) return;
    const message: ClientMessage = {
      type: "audio.chunk",
      session_id: sessionId,
      sequence: chunk.sequence,
      timestamp_ms: chunk.timestampMs,
      payload_b64: chunk.payloadB64,
      sample_rate: chunk.sampleRate,
      channels: chunk.channels,
    };
    ws.send(JSON.stringify(message));
  }, []);

  const runDemoLoop = useCallback(async () => {
    const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
    while (!demoCancelRef.current) {
      if (isMutedRef.current) {
        await sleep(300);
        continue;
      }
      const script = nextDemoScript();
      const utteranceId = `utt-${Date.now()}`;
      dispatch({ kind: "stage", stage: "listening" });

      for (const step of partialSteps(script.raw)) {
        if (demoCancelRef.current) return;
        await sleep(step.delayMs);
        dispatch({
          kind: "server-event",
          event: {
            type: "transcript.partial",
            version: 1,
            session_id: sessionIdRef.current ?? "",
            utterance_id: utteranceId,
            text: step.text,
            is_final: false,
            confidence: null,
            start_ms: 0,
            end_ms: 0,
          },
        });
      }
      if (demoCancelRef.current) return;
      dispatch({
        kind: "server-event",
        event: {
          type: "transcript.final",
          version: 1,
          session_id: sessionIdRef.current ?? "",
          utterance_id: utteranceId,
          text: script.raw,
          is_final: true,
          confidence: 0.92,
          start_ms: 0,
          end_ms: 0,
        },
      });

      dispatch({ kind: "stage", stage: "repairing" });
      await sleep(650);
      if (demoCancelRef.current) return;
      dispatch({
        kind: "server-event",
        event: {
          type: "repair.completed",
          version: 1,
          session_id: sessionIdRef.current ?? "",
          utterance_id: utteranceId,
          original_text: script.raw,
          repaired_text: script.repaired,
          confidence: 0.87,
          changes: script.changes,
        },
      });

      dispatch({ kind: "stage", stage: "validating" });
      await sleep(400);
      if (demoCancelRef.current) return;
      const spokenText = script.approved ? script.repaired : script.raw;
      dispatch({
        kind: "server-event",
        event: {
          type: "validation.result",
          session_id: sessionIdRef.current ?? "",
          utterance_id: utteranceId,
          approved: script.approved,
          reason: script.reason,
          source: script.approved ? "repaired" : "original",
          spoken_text: spokenText,
        },
      });

      dispatch({ kind: "stage", stage: "speaking" });
      if (onDemoSpeak) await onDemoSpeak(spokenText);
      if (demoCancelRef.current) return;
      dispatch({ kind: "stage", stage: "listening" });
      await sleep(900);
    }
  }, [onDemoSpeak]);

  const startSession = useCallback(() => {
    const sessionId = makeSessionId();
    sessionIdRef.current = sessionId;
    dispatch({ kind: "session-start", sessionId });

    if (useDemoMode || !wsUrl) {
      demoCancelRef.current = false;
      dispatch({ kind: "connection", status: "demo" });
      void runDemoLoop();
      return;
    }

    dispatch({ kind: "connection", status: "connecting" });
    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      ws.onopen = () => {
        dispatch({ kind: "connection", status: "online" });
        const message: ClientMessage = {
          type: "session.start",
          session_id: sessionId,
          sample_rate: 16000,
          channels: 1,
        };
        ws.send(JSON.stringify(message));
      };
      ws.onmessage = (event) => {
        try {
          const parsed: ServerEvent = JSON.parse(event.data);
          if (
            (parsed.type === "audio.chunk" || parsed.type === "audio.final") &&
            onAudioOutputChunk
          ) {
            onAudioOutputChunk(parsed.audio_chunk_b64, parsed.is_final);
          }
          dispatch({ kind: "server-event", event: parsed });
        } catch {
          // ignore malformed frames
        }
      };
      ws.onerror = () => {
        dispatch({ kind: "error", message: "WebSocket connection error." });
      };
      ws.onclose = () => {
        dispatch({ kind: "connection", status: "offline" });
      };
    } catch (err) {
      dispatch({ kind: "error", message: err instanceof Error ? err.message : "Failed to connect." });
      dispatch({ kind: "connection", status: "offline" });
    }
  }, [onAudioOutputChunk, runDemoLoop, useDemoMode, wsUrl]);

  const stopSession = useCallback(() => {
    demoCancelRef.current = true;
    const ws = wsRef.current;
    const sessionId = sessionIdRef.current;
    if (ws && ws.readyState === WebSocket.OPEN && sessionId) {
      const message: ClientMessage = { type: "session.stop", session_id: sessionId };
      ws.send(JSON.stringify(message));
    }
    ws?.close();
    wsRef.current = null;
    sessionIdRef.current = null;
    dispatch({ kind: "connection", status: "offline" });
    dispatch({ kind: "session-stop" });
  }, []);

  const toggleMute = useCallback(() => {
    isMutedRef.current = !isMutedRef.current;
    dispatch({ kind: "mute", muted: isMutedRef.current });
    const ws = wsRef.current;
    const sessionId = sessionIdRef.current;
    if (ws && ws.readyState === WebSocket.OPEN && sessionId) {
      const message: ClientMessage = { type: "session.mute", session_id: sessionId, muted: isMutedRef.current };
      ws.send(JSON.stringify(message));
    }
  }, []);

  const cancelSpeech = useCallback(() => {
    const ws = wsRef.current;
    const sessionId = sessionIdRef.current;
    if (ws && ws.readyState === WebSocket.OPEN && sessionId) {
      const message: ClientMessage = { type: "playback.cancel", session_id: sessionId };
      ws.send(JSON.stringify(message));
    }
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    dispatch({ kind: "stage", stage: "listening" });
  }, []);

  const clearHistory = useCallback(() => dispatch({ kind: "clear-history" }), []);

  return {
    state,
    startSession,
    stopSession,
    toggleMute,
    cancelSpeech,
    clearHistory,
    sendAudioChunk,
    demoScriptCount: DEMO_SCRIPTS.length,
  };
}
