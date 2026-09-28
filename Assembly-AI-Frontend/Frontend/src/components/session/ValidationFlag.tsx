import { AlertTriangle, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ValidationReason } from "@/lib/ws/types";

const REASON_LABEL: Record<ValidationReason, string> = {
  approved: "Repair approved",
  number_changed: "Fell back — a number changed meaning",
  date_changed: "Fell back — a date changed meaning",
  entity_changed: "Fell back — a name/entity changed",
  negation_changed: "Fell back — negation changed meaning",
  semantic_risk: "Fell back — meaning risk detected",
  invalid_output: "Fell back — repair output was invalid",
};

interface ValidationFlagProps {
  approved: boolean | null;
  reason: ValidationReason | null;
  source: "repaired" | "safer" | "original" | null;
}

export function ValidationFlag({ approved, reason, source }: ValidationFlagProps) {
  if (approved === null || reason === null) {
    return <span className="text-xs text-subtle-foreground">Awaiting validation…</span>;
  }

  return (
    <div
      className={cn(
        "flex items-center gap-1.5 text-xs font-medium",
        approved ? "text-profit" : "text-warning"
      )}
    >
      {approved ? <ShieldCheck size={14} /> : <AlertTriangle size={14} />}
      <span>{REASON_LABEL[reason]}</span>
      {!approved && source && <span className="text-subtle-foreground">· spoke {source} text</span>}
    </div>
  );
}
