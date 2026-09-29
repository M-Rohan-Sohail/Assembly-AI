"use client";

import { useCallback, useRef, useState } from "react";

const PLAYBACK_SAMPLE_RATE = 16000;

function base64ToInt16(base64: string): Int16Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Int16Array(bytes.buffer);
}

/**
 * Plays TTS output two ways depending on source:
 *  - real backend: raw PCM16LE/16kHz chunks (see tts/tts_config.json
 *    audio_format) scheduled back-to-back on a shared AudioContext.
 *  - demo mode: no backend audio exists, so it speaks the text aloud via
 *    the browser's built-in SpeechSynthesis API instead.
 */
export function useSpeechPlayback() {
  const [isSpeaking, setIsSpeaking] = useState(false);
  const contextRef = useRef<AudioContext | null>(null);
  const nextStartRef = useRef(0);
  const pendingSourcesRef = useRef<AudioBufferSourceNode[]>([]);

  const ensureContext = useCallback(() => {
    if (!contextRef.current) {
      const Ctor =
        window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      contextRef.current = new Ctor();
      nextStartRef.current = 0;
    }
    if (contextRef.current.state === "suspended") {
      contextRef.current.resume().catch(() => {});
    }
    return contextRef.current;
  }, []);

  const playPcmChunk = useCallback(
    (base64: string, isFinal: boolean) => {
      if (!base64) {
        if (isFinal) setIsSpeaking(false);
        return;
      }
      const context = ensureContext();
      if (context.state === "suspended") {
        context.resume().catch(() => {});
      }
      const samples = base64ToInt16(base64);
      const float32 = new Float32Array(samples.length);
      for (let i = 0; i < samples.length; i++) float32[i] = samples[i] / 0x8000;

      const buffer = context.createBuffer(1, float32.length, PLAYBACK_SAMPLE_RATE);
      buffer.copyToChannel(float32, 0);

      const source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(context.destination);

      const startAt = Math.max(context.currentTime, nextStartRef.current);
      source.start(startAt);
      nextStartRef.current = startAt + buffer.duration;
      pendingSourcesRef.current.push(source);
      setIsSpeaking(true);

      source.onended = () => {
        pendingSourcesRef.current = pendingSourcesRef.current.filter((s) => s !== source);
        if (isFinal && pendingSourcesRef.current.length === 0) setIsSpeaking(false);
      };
    },
    [ensureContext]
  );

  const speakWithBrowserTts = useCallback(
    (text: string, voice?: SpeechSynthesisVoice | null): Promise<void> => {
      return new Promise((resolve) => {
        if (typeof window === "undefined" || !("speechSynthesis" in window) || !text) {
          resolve();
          return;
        }
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        if (voice) utterance.voice = voice;
        utterance.onstart = () => setIsSpeaking(true);
        utterance.onend = () => {
          setIsSpeaking(false);
          resolve();
        };
        utterance.onerror = () => {
          setIsSpeaking(false);
          resolve();
        };
        window.speechSynthesis.speak(utterance);
      });
    },
    []
  );

  const cancel = useCallback(() => {
    pendingSourcesRef.current.forEach((s) => {
      try {
        s.stop();
      } catch {
        // already stopped
      }
    });
    pendingSourcesRef.current = [];
    nextStartRef.current = 0;
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    setIsSpeaking(false);
  }, []);

  return { isSpeaking, playPcmChunk, speakWithBrowserTts, cancel };
}
