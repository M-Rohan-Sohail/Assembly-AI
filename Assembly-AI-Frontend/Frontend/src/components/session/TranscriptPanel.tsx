import { cn } from "@/lib/utils";

interface TranscriptPanelProps {
  title: string;
  text: string;
  placeholder: string;
  accent?: "neutral" | "accent";
  isFinal?: boolean;
  headerRight?: React.ReactNode;
  children?: React.ReactNode;
}

export function TranscriptPanel({
  title,
  text,
  placeholder,
  accent = "neutral",
  isFinal,
  headerRight,
  children,
}: TranscriptPanelProps) {
  return (
    <div className="flex min-h-[220px] flex-1 flex-col rounded-xl border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "h-1.5 w-1.5 rounded-full",
              accent === "accent" ? "bg-accent" : "bg-subtle-foreground"
            )}
          />
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
          {text && !isFinal && (
            <span className="text-[10px] font-medium text-subtle-foreground">live…</span>
          )}
        </div>
        {headerRight}
      </div>
      <div className="flex-1 px-4 py-3">
        {text ? (
          <p className="whitespace-pre-wrap text-[15px] leading-relaxed text-foreground">{text}</p>
        ) : (
          <p className="text-sm text-subtle-foreground">{placeholder}</p>
        )}
      </div>
      {children && <div className="border-t border-border px-4 py-2.5">{children}</div>}
    </div>
  );
}
