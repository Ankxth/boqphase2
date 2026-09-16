import { ChevronDown } from "lucide-react";
import { useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import clsx from "clsx";

export function Accordion({
  title,
  subtitle,
  children,
  defaultOpen = false,
  tone = "neutral",
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  tone?: "neutral" | "amber" | "rust";
}) {
  const [open, setOpen] = useState(defaultOpen);
  const toneClass = { neutral: "", amber: "border-l-2 border-l-amber", rust: "border-l-2 border-l-rust" }[tone];

  return (
    <div className={clsx("overflow-hidden rounded-xl border border-line bg-bg-raised/60", toneClass)}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <div>
          <div className="text-[13.5px] font-medium text-ink">{title}</div>
          {subtitle && <div className="mt-0.5 text-[12px] text-ink-faint">{subtitle}</div>}
        </div>
        <motion.span animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.2 }} className="shrink-0 text-ink-faint">
          <ChevronDown size={16} />
        </motion.span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div className="border-t border-line px-4 py-3.5 text-[13px] leading-relaxed text-ink-soft">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
