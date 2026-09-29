"use client";

import { Mic, Square } from "lucide-react";
import { cn } from "@/lib/utils";
import type { PipelineStage } from "@/lib/ws/types";
import { Waveform } from "./Waveform";

interface RecordButtonProps {
  isActive: boolean;
  stage: PipelineStage;
  analyser: AnalyserNode | null;
  onToggle: () => void;
  disabled?: boolean;
}

export function RecordButton({ isActive, stage, analyser, onToggle, disabled }: RecordButtonProps) {
  return (
    <div className="flex flex-col items-center gap-4">
      <button
        onClick={onToggle}
        disabled={disabled}
        aria-pressed={isActive}
        aria-label={isActive ? "Stop session" : "Start session"}
        className={cn(
          "relative flex h-40 w-40 items-center justify-center rounded-full border-4 transition-all disabled:opacity-40 disabled:pointer-events-none",
          isActive
            ? "border-loss/60 bg-loss-bg shadow-[0_0_0_10px_rgba(239,68,68,0.08)]"
            : "border-accent/60 bg-accent-bg shadow-[0_0_0_10px_rgba(59,130,246,0.08)] hover:border-accent"
        )}
      >
        {isActive && (
          <div className="absolute inset-3 overflow-hidden rounded-full opacity-70">
            <Waveform analyser={analyser} active={isActive} color={stage === "speaking" ? "#10b981" : "#3b82f6"} />
          </div>
        )}
        <div className="relative z-10 flex h-16 w-16 items-center justify-center rounded-full bg-surface shadow-md">
          {isActive ? <Square size={22} className="text-loss" fill="currentColor" /> : <Mic size={26} className="text-accent" />}
        </div>
      </button>
      <span className="text-sm text-muted-foreground">
        {isActive ? "Tap to stop" : "Tap to start speaking"}
      </span>
    </div>
  );
}
