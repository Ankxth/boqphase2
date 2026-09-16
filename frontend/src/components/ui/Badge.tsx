import clsx from "clsx";
import type { ReactNode } from "react";
import type { FieldSource } from "../../lib/types";

type Tone = "coral" | "moss" | "amber" | "rust" | "neutral";

const TONES: Record<Tone, string> = {
  coral: "bg-coral-soft text-coral",
  moss: "bg-moss-soft text-moss",
  amber: "bg-amber-soft text-amber",
  rust: "bg-rust-soft text-rust",
  neutral: "bg-white/[0.06] text-ink-soft",
};

export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-1 font-mono text-[10px] font-medium uppercase tracking-[0.08em]",
        TONES[tone],
        className
      )}
    >
      {children}
    </span>
  );
}

const SOURCE_TONE: Record<FieldSource, Tone> = {
  "user-entered": "moss",
  "boq-matched": "coral",
  "own-boq-extracted": "coral",
  "llm-estimated": "amber",
  unset: "neutral",
};

const SOURCE_LABEL: Record<FieldSource, string> = {
  "user-entered": "You entered this",
  "boq-matched": "Matched from a reference BOQ",
  "own-boq-extracted": "Extracted from your BOQ",
  "llm-estimated": "Estimated",
  unset: "Not set",
};

export function SourceBadge({ source, confidence }: { source: FieldSource; confidence?: number }) {
  const label = SOURCE_LABEL[source] + (confidence != null && confidence > 0 && source !== "user-entered" ? ` · ${Math.round(confidence * 100)}%` : "");
  return (
    <Badge tone={SOURCE_TONE[source]} className="normal-case tracking-normal">
      {label}
    </Badge>
  );
}
