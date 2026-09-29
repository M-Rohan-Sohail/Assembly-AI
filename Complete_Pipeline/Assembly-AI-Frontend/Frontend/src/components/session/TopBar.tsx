import { AudioLines, Settings } from "lucide-react";
import { IconButton } from "@/components/ui/IconButton";
import { StatusBadge, ConnectionIndicator } from "./StatusBadge";
import type { PipelineStage } from "@/lib/ws/types";
import type { ConnectionStatus } from "@/lib/ws/session-types";

interface TopBarProps {
  stage: PipelineStage;
  connection: ConnectionStatus;
  onOpenSettings: () => void;
}

export function TopBar({ stage, connection, onOpenSettings }: TopBarProps) {
  return (
    <header className="flex items-center justify-between border-b border-border px-6 py-4">
      <div className="flex items-center gap-2.5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-bg text-accent">
          <AudioLines size={18} />
        </div>
        <div>
          <h1 className="text-sm font-semibold text-foreground">ClearVoice 2.0</h1>
          <ConnectionIndicator status={connection} />
        </div>
      </div>
      <div className="flex items-center gap-3">
        <StatusBadge stage={stage} />
        <IconButton label="Settings" onClick={onOpenSettings}>
          <Settings size={17} />
        </IconButton>
      </div>
    </header>
  );
}
