import { motion } from "framer-motion";
import type { ReactNode } from "react";
import clsx from "clsx";

export function StatTile({
  label,
  value,
  sub,
  icon,
  tone = "coral",
  delay = 0,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  icon?: ReactNode;
  tone?: "coral" | "moss" | "amber";
  delay?: number;
}) {
  const toneClass = { coral: "text-coral", moss: "text-moss", amber: "text-amber" }[tone];
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay, ease: [0.16, 1, 0.3, 1] }}
      className="neu-raised rounded-2xl border border-line bg-bg-card/80 p-5"
    >
      <div className="flex items-center justify-between">
        <div className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-faint">{label}</div>
        {icon && <div className={clsx("opacity-80", toneClass)}>{icon}</div>}
      </div>
      <div className="mt-2 font-display text-[1.9rem] leading-none text-ink tabular">{value}</div>
      {sub && <div className="mt-1.5 text-[12.5px] text-ink-soft">{sub}</div>}
    </motion.div>
  );
}
