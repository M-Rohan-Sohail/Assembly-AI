import { cn } from "@/lib/utils";
import type { PipelineStage } from "@/lib/ws/types";
import type { ConnectionStatus } from "@/lib/ws/session-types";

const STAGE_LABEL: Record<PipelineStage, string> = {
  idle: "Idle",
  listening: "Listening",
  repairing: "Repairing",
  validating: "Validating",
  speaking: "Speaking",
};

const STAGE_DOT: Record<PipelineStage, string> = {
  idle: "bg-neutral",
  listening: "bg-info",
  repairing: "bg-warning",
  validating: "bg-warning",
  speaking: "bg-profit",
};

export function StatusBadge({ stage }: { stage: PipelineStage }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1 text-xs font-medium text-foreground">
      <span className={cn("h-2 w-2 rounded-full", STAGE_DOT[stage], stage !== "idle" && "animate-pulse")} />
      {STAGE_LABEL[stage]}
    </span>
  );
}

const CONNECTION_LABEL: Record<ConnectionStatus, string> = {
  offline: "Not connected",
  connecting: "Connecting…",
  online: "Backend connected",
  demo: "Demo mode",
};

const CONNECTION_COLOR: Record<ConnectionStatus, string> = {
  offline: "text-subtle-foreground",
  connecting: "text-warning",
  online: "text-profit",
  demo: "text-info",
};

export function ConnectionIndicator({ status }: { status: ConnectionStatus }) {
  return <span className={cn("text-xs font-medium", CONNECTION_COLOR[status])}>{CONNECTION_LABEL[status]}</span>;
}
