import clsx from "clsx";
import type { HTMLAttributes, ReactNode } from "react";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  accent?: "coral" | "moss" | "amber" | "none";
  raised?: boolean;
}

const ACCENT_BORDER: Record<string, string> = {
  coral: "border-l-2 border-l-coral",
  moss: "border-l-2 border-l-moss",
  amber: "border-l-2 border-l-amber",
  none: "",
};

export function Card({ children, className, accent = "none", raised = true, ...rest }: CardProps) {
  return (
    <div
      className={clsx(
        "rounded-2xl border border-line bg-bg-card/80 p-5",
        raised && "neu-raised",
        ACCENT_BORDER[accent],
        className
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

export function CardLabel({ children }: { children: ReactNode }) {
  return (
    <div className="mb-2 font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-faint">
      {children}
    </div>
  );
}
