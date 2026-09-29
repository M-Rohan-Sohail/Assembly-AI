"use client";

import { useCallback, useReducer, useRef, useEffect } from "react";
import { makeSessionId } from "@/lib/utils";
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
      return { ...state, sessionId: action.sessionId, stage: "listening", error: null };
    case "session-stop":
      return { ...state, stage: "idle", sessionId: null };
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
          let history = state.history;
          if (state.current && state.current.utteranceId !== event.utterance_id) {
            if (state.current.repairedText || state.current.rawText) {
              const alreadyInHistory = history.some((h) => h.utteranceId === state.current!.utteranceId);
              if (!alreadyInHistory) {
                history = [state.current, ...history].slice(0, MAX_HISTORY);
              }
            }
          }
          const current = upsertCurrent(state, event.utterance_id);
          const updated: UtteranceRecord = {
            ...current,
            rawText: event.text,
            isFinal: event.is_final,
            updatedAt: Date.now(),
          };
          return { ...state, current: updated, history };
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
          const filteredHistory = state.history.filter((h) => h.utteranceId !== event.utterance_id);
          const history = [finalized, ...filteredHistory].slice(0, MAX_HISTORY);
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
  onAudioOutputChunk?: (audioChunkB64: string, isFinal: boolean) => void;
  onFallbackSpeak?: (text: string) => Promise<void>;
}

export function useClearVoiceSession(options: UseClearVoiceSessionOptions) {
  const { wsUrl, onAudioOutputChunk, onFallbackSpeak } = options;
  const [state, dispatch] = useReducer(reducer, initialSessionState);
  const wsRef = useRef<WebSocket | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const isMutedRef = useRef(false);

  const onAudioOutputChunkRef = useRef(onAudioOutputChunk);
  useEffect(() => {
    onAudioOutputChunkRef.current = onAudioOutputChunk;
  });

  const onFallbackSpeakRef = useRef(onFallbackSpeak);
  useEffect(() => {
    onFallbackSpeakRef.current = onFallbackSpeak;
  });

  const audioReceivedForCurrentUtteranceRef = useRef(false);
  const fallbackTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSpokenTextRef = useRef<string>("");

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

  // Persistent WebSocket connection on page load
  useEffect(() => {
    if (!wsUrl) {
      dispatch({ kind: "connection", status: "offline" });
      dispatch({ kind: "error", message: "NEXT_PUBLIC_WS_URL is not configured." });
      return;
    }

    let isUnmounted = false;
    let reconnectTimeout: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      if (isUnmounted) return;
      if (
        wsRef.current &&
        (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)
      ) {
        return;
      }

      dispatch({ kind: "connection", status: "connecting" });
      try {
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
          if (isUnmounted) {
            ws.close();
            return;
          }
          dispatch({ kind: "connection", status: "online" });
          dispatch({ kind: "error", message: null });
        };

        ws.onmessage = (event) => {
          if (isUnmounted) return;
          try {
            const parsed: ServerEvent = JSON.parse(event.data);

            if (parsed.type === "transcript.final") {
              audioReceivedForCurrentUtteranceRef.current = false;
            }

            if (parsed.type === "validation.result") {
              audioReceivedForCurrentUtteranceRef.current = false;
              lastSpokenTextRef.current = parsed.spoken_text;
              if (fallbackTimeoutRef.current) {
                clearTimeout(fallbackTimeoutRef.current);
              }
              const textToSpeak = parsed.spoken_text;
              // If backend ElevenLabs/System audio chunks don't arrive within 1200ms, fall back to browser system voice!
              fallbackTimeoutRef.current = setTimeout(() => {
                if (!audioReceivedForCurrentUtteranceRef.current && onFallbackSpeakRef.current && textToSpeak) {
                  console.log("No backend audio chunks received within 1200ms; falling back to browser system voice:", textToSpeak);
                  void onFallbackSpeakRef.current(textToSpeak);
                }
              }, 1200);
            }

            if (parsed.type === "audio.chunk" || parsed.type === "audio.final") {
              if (parsed.audio_chunk_b64) {
                audioReceivedForCurrentUtteranceRef.current = true;
                if (fallbackTimeoutRef.current) {
                  clearTimeout(fallbackTimeoutRef.current);
                  fallbackTimeoutRef.current = null;
                }
              }
              if (onAudioOutputChunkRef.current) {
                onAudioOutputChunkRef.current(parsed.audio_chunk_b64, parsed.is_final);
              }
            }

            if (parsed.type === "pipeline.error" && parsed.stage === "tts") {
              if (fallbackTimeoutRef.current) {
                clearTimeout(fallbackTimeoutRef.current);
                fallbackTimeoutRef.current = null;
              }
              if (!audioReceivedForCurrentUtteranceRef.current && onFallbackSpeakRef.current && lastSpokenTextRef.current) {
                console.warn("Backend TTS reported error; immediately falling back to browser system voice:", lastSpokenTextRef.current);
                void onFallbackSpeakRef.current(lastSpokenTextRef.current);
              }
            }

            dispatch({ kind: "server-event", event: parsed });
          } catch {
            // ignore malformed frames
          }
        };

        ws.onerror = () => {
          if (isUnmounted) return;
        };

        ws.onclose = () => {
          wsRef.current = null;
          if (isUnmounted) return;
          dispatch({ kind: "connection", status: "offline" });
          reconnectTimeout = setTimeout(connect, 3000);
        };
      } catch (err) {
        wsRef.current = null;
        if (!isUnmounted) {
          dispatch({ kind: "error", message: err instanceof Error ? err.message : "Failed to connect." });
          dispatch({ kind: "connection", status: "offline" });
          reconnectTimeout = setTimeout(connect, 3000);
        }
      }
    };

    connect();

    return () => {
      isUnmounted = true;
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      if (fallbackTimeoutRef.current) clearTimeout(fallbackTimeoutRef.current);
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [wsUrl]);

  const startSession = useCallback(() => {
    const sessionId = makeSessionId();
    sessionIdRef.current = sessionId;
    dispatch({ kind: "session-start", sessionId });

    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      const message: ClientMessage = {
        type: "session.start",
        session_id: sessionId,
        sample_rate: 16000,
        channels: 1,
      };
      ws.send(JSON.stringify(message));
    }
  }, []);

  const stopSession = useCallback(() => {
    if (fallbackTimeoutRef.current) {
      clearTimeout(fallbackTimeoutRef.current);
      fallbackTimeoutRef.current = null;
    }
    const ws = wsRef.current;
    const sessionId = sessionIdRef.current;
    if (ws && ws.readyState === WebSocket.OPEN && sessionId) {
      const message: ClientMessage = { type: "session.stop", session_id: sessionId };
      ws.send(JSON.stringify(message));
    }
    sessionIdRef.current = null;
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
    if (fallbackTimeoutRef.current) {
      clearTimeout(fallbackTimeoutRef.current);
      fallbackTimeoutRef.current = null;
    }
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
  };
}
