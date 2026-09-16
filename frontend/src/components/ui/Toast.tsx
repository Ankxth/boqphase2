import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

type ToastKind = "success" | "error" | "info";

interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
}

interface ToastContextValue {
  push: (kind: ToastKind, message: string) => void;
}

const ToastContext = createContext<ToastContextValue>({ push: () => {} });

export function useToast() {
  const ctx = useContext(ToastContext);
  return {
    success: (m: string) => ctx.push("success", m),
    error: (m: string) => ctx.push("error", m),
    info: (m: string) => ctx.push("info", m),
  };
}

const ICONS: Record<ToastKind, ReactNode> = {
  success: <CheckCircle2 size={17} className="text-moss shrink-0" />,
  error: <AlertTriangle size={17} className="text-rust shrink-0" />,
  info: <Info size={17} className="text-coral shrink-0" />,
};

const BORDER: Record<ToastKind, string> = {
  success: "border-l-moss",
  error: "border-l-rust",
  info: "border-l-coral",
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const push = useCallback((kind: ToastKind, message: string) => {
    const id = Date.now() + Math.random();
    setItems((prev) => [...prev, { id, kind, message }]);
    window.setTimeout(() => {
      setItems((prev) => prev.filter((t) => t.id !== id));
    }, kind === "error" ? 7000 : 4200);
  }, []);

  return (
    <ToastContext.Provider value={{ push }}>
      {children}
      <div className="fixed bottom-5 right-5 z-[100] flex w-[min(380px,calc(100vw-2.5rem))] flex-col gap-2">
        <AnimatePresence>
          {items.map((t) => (
            <motion.div
              key={t.id}
              initial={{ opacity: 0, y: 16, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, x: 40, transition: { duration: 0.18 } }}
              transition={{ type: "spring", stiffness: 340, damping: 28 }}
              className={`neu-raised flex items-start gap-2.5 rounded-xl border-l-2 bg-bg-card/95 px-3.5 py-3 text-[13px] leading-snug text-ink backdrop-blur ${BORDER[t.kind]}`}
            >
              {ICONS[t.kind]}
              <span className="flex-1">{t.message}</span>
              <button
                onClick={() => setItems((prev) => prev.filter((x) => x.id !== t.id))}
                className="text-ink-faint hover:text-ink"
                aria-label="Dismiss"
              >
                <X size={14} />
              </button>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}
