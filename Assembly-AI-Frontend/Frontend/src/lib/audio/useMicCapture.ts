"use client";

import { useCallback, useRef, useState } from "react";

const TARGET_SAMPLE_RATE = 16000;

export interface AudioChunkPayload {
  payloadB64: string;
  sampleRate: number;
  channels: number;
  timestampMs: number;
  sequence: number;
}

export interface MicDevice {
  deviceId: string;
  label: string;
}

interface UseMicCaptureOptions {
  onAudioChunk?: (chunk: AudioChunkPayload) => void;
}

function floatTo16BitPcm(input: Float32Array): Int16Array {
  const output = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]));
    output[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return output;
}

function downsample(input: Float32Array, inputRate: number, outputRate: number): Float32Array {
  if (outputRate >= inputRate) return input;
  const ratio = inputRate / outputRate;
  const outputLength = Math.floor(input.length / ratio);
  const result = new Float32Array(outputLength);
  for (let i = 0; i < outputLength; i++) {
    result[i] = input[Math.floor(i * ratio)];
  }
  return result;
}

function bufferToBase64(buffer: Int16Array): string {
  const bytes = new Uint8Array(buffer.buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

/**
 * Captures the mic, exposes a live AnalyserNode for waveform rendering, and
 * (optionally) streams downsampled PCM16 chunks via onAudioChunk for a real
 * WebSocket backend.
 */
export function useMicCapture({ onAudioChunk }: UseMicCaptureOptions = {}) {
  const [isActive, setIsActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [devices, setDevices] = useState<MicDevice[]>([]);

  const streamRef = useRef<MediaStream | null>(null);
  const contextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const sequenceRef = useRef(0);

  const refreshDevices = useCallback(async () => {
    try {
      const list = await navigator.mediaDevices.enumerateDevices();
      setDevices(
        list
          .filter((d) => d.kind === "audioinput")
          .map((d, i) => ({ deviceId: d.deviceId, label: d.label || `Microphone ${i + 1}` }))
      );
    } catch {
      // enumerateDevices can fail before permission is granted; ignore.
    }
  }, []);

  const stop = useCallback(() => {
    processorRef.current?.disconnect();
    processorRef.current = null;
    analyserRef.current?.disconnect();
    analyserRef.current = null;
    contextRef.current?.close().catch(() => {});
    contextRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    sequenceRef.current = 0;
    setIsActive(false);
  }, []);

  const start = useCallback(
    async (deviceId?: string) => {
      setError(null);
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: deviceId ? { deviceId: { exact: deviceId } } : true,
        });
        streamRef.current = stream;

        const AudioContextCtor =
          window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
        const context = new AudioContextCtor();
        contextRef.current = context;

        const source = context.createMediaStreamSource(stream);
        const analyser = context.createAnalyser();
        analyser.fftSize = 256;
        analyser.smoothingTimeConstant = 0.75;
        analyserRef.current = analyser;
        source.connect(analyser);

        if (onAudioChunk) {
          const processor = context.createScriptProcessor(4096, 1, 1);
          processorRef.current = processor;
          processor.onaudioprocess = (event) => {
            const input = event.inputBuffer.getChannelData(0);
            const resampled = downsample(input, context.sampleRate, TARGET_SAMPLE_RATE);
            const pcm16 = floatTo16BitPcm(resampled);
            onAudioChunk({
              payloadB64: bufferToBase64(pcm16),
              sampleRate: TARGET_SAMPLE_RATE,
              channels: 1,
              timestampMs: Date.now(),
              sequence: sequenceRef.current++,
            });
          };
          // ScriptProcessorNode only fires onaudioprocess while connected
          // to a destination; route it through a silent gain node so the
          // raw mic signal is never actually played back.
          const silentSink = context.createGain();
          silentSink.gain.value = 0;
          source.connect(processor);
          processor.connect(silentSink);
          silentSink.connect(context.destination);
        }

        await refreshDevices();
        setIsActive(true);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Microphone access failed.");
        stop();
      }
    },
    [onAudioChunk, refreshDevices, stop]
  );

  return { start, stop, isActive, error, devices, refreshDevices, analyserRef };
}
