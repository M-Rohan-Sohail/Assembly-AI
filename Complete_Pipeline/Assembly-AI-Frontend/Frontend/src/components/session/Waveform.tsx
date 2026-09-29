"use client";

import { useEffect, useRef } from "react";

interface WaveformProps {
  analyser: AnalyserNode | null;
  active: boolean;
  color?: string;
}

export function Waveform({ analyser, active, color = "#3b82f6" }: WaveformProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const frameRef = useRef<number>(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.scale(dpr, dpr);

    const bufferLength = analyser?.frequencyBinCount ?? 128;
    const data = new Uint8Array(bufferLength);

    const draw = () => {
      frameRef.current = requestAnimationFrame(draw);
      ctx.clearRect(0, 0, width, height);

      if (analyser && active) {
        analyser.getByteFrequencyData(data);
      } else {
        data.fill(0);
      }

      const barCount = 32;
      const step = Math.floor(data.length / barCount) || 1;
      const barWidth = width / barCount;
      ctx.fillStyle = color;

      for (let i = 0; i < barCount; i++) {
        const value = active ? data[i * step] / 255 : 0.04;
        const barHeight = Math.max(2, value * height);
        const x = i * barWidth;
        const y = (height - barHeight) / 2;
        ctx.globalAlpha = active ? 0.55 + value * 0.45 : 0.25;
        ctx.fillRect(x + barWidth * 0.2, y, barWidth * 0.6, barHeight);
      }
    };

    draw();
    return () => cancelAnimationFrame(frameRef.current);
  }, [analyser, active, color]);

  return <canvas ref={canvasRef} className="h-full w-full" />;
}
