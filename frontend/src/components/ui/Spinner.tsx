import { Loader2 } from "lucide-react";

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2.5 py-10 text-ink-soft">
      <Loader2 size={18} className="animate-spin text-coral" />
      <span className="text-[13.5px]">{label ?? "Loading…"}</span>
    </div>
  );
}

export function SpinnerInline({ size = 14 }: { size?: number }) {
  return <Loader2 size={size} className="animate-spin" />;
}
