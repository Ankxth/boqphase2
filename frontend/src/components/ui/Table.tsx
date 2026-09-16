import type { ReactNode } from "react";

export function Table({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-line">
      <table className="w-full min-w-[560px] border-collapse text-[12.5px]">{children}</table>
    </div>
  );
}

export function THead({ children }: { children: ReactNode }) {
  return <thead className="bg-bg-raised/80">{children}</thead>;
}

export function Th({ children, align = "left" }: { children: ReactNode; align?: "left" | "right" }) {
  return (
    <th
      className={`border-b border-line-strong px-3.5 py-2.5 font-mono text-[10px] font-medium uppercase tracking-[0.08em] text-ink-faint ${
        align === "right" ? "text-right" : "text-left"
      }`}
    >
      {children}
    </th>
  );
}

export function Td({
  children,
  align = "left",
  className = "",
  title,
}: {
  children: ReactNode;
  align?: "left" | "right";
  className?: string;
  title?: string;
}) {
  return (
    <td title={title} className={`border-b border-line px-3.5 py-2.5 text-ink ${align === "right" ? "text-right tabular" : "text-left"} ${className}`}>
      {children}
    </td>
  );
}
