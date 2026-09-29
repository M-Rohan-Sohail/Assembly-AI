"use client";

import { useState } from "react";
import { ChevronDown, History } from "lucide-react";
import { cn, formatClock } from "@/lib/utils";
import type { UtteranceRecord } from "@/lib/ws/session-types";
import { ValidationFlag } from "./ValidationFlag";

export function HistoryList({ items }: { items: UtteranceRecord[] }) {
  const [open, setOpen] = useState(true);

  return (
    <div className="rounded-xl border border-border bg-surface">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-4 py-3"
      >
        <div className="flex items-center gap-2">
          <History size={14} className="text-muted-foreground" />
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Session history
          </span>
          <span className="rounded-full bg-surface-hover px-1.5 py-0.5 text-[10px] text-subtle-foreground">
            {items.length}
          </span>
        </div>
        <ChevronDown
          size={16}
          className={cn("text-muted-foreground transition-transform", open && "rotate-180")}
        />
      </button>
      {open && (
        <div className="max-h-72 overflow-y-auto border-t border-border">
          {items.length === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-subtle-foreground">
              Past utterances will appear here.
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {items.map((item) => (
                <li key={item.utteranceId} className="px-4 py-3">
                  <div className="mb-1 flex items-center justify-between">
                    <span className="text-[11px] text-subtle-foreground">{formatClock(item.updatedAt)}</span>
                  </div>
                  <p className="text-sm text-foreground">{item.repairedText || item.rawText}</p>
                  {item.rawText !== item.repairedText && (
                    <p className="mt-0.5 text-xs text-subtle-foreground line-through decoration-subtle-foreground/50">
                      {item.rawText}
                    </p>
                  )}
                  <div className="mt-1.5">
                    <ValidationFlag approved={item.approved} reason={item.reason} source={item.source} />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
