import clsx from "clsx";
import { motion } from "framer-motion";
import type { ReactNode } from "react";

export interface TabItem {
  id: string;
  label: string;
  icon?: ReactNode;
  disabled?: boolean;
}

export function Tabs({ items, active, onChange }: { items: TabItem[]; active: string; onChange: (id: string) => void }) {
  return (
    <div className="neu-inset flex gap-1 overflow-x-auto rounded-full border border-line bg-bg-inset p-1.5">
      {items.map((t) => {
        const isActive = t.id === active;
        return (
          <button
            key={t.id}
            disabled={t.disabled}
            onClick={() => onChange(t.id)}
            className={clsx(
              "relative flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-3.5 py-2 text-[12.5px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-35",
              isActive ? "text-bg" : "text-ink-soft hover:text-ink"
            )}
          >
            {isActive && (
              <motion.span
                layoutId="tab-pill"
                className="absolute inset-0 rounded-full bg-coral"
                transition={{ type: "spring", stiffness: 420, damping: 34 }}
              />
            )}
            <span className="relative z-10 flex items-center gap-1.5">
              {t.icon}
              {t.label}
            </span>
          </button>
        );
      })}
    </div>
  );
}
