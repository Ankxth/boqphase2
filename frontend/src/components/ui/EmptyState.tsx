import type { ReactNode } from "react";

export function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon?: ReactNode;
  title: string;
  body?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-line px-6 py-14 text-center">
      {icon && <div className="text-ink-faint opacity-70">{icon}</div>}
      <div className="font-display text-lg text-ink">{title}</div>
      {body && <div className="max-w-sm text-[13px] leading-relaxed text-ink-soft">{body}</div>}
      {action}
    </div>
  );
}
