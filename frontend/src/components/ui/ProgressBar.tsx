import clsx from "clsx";

export function ProgressBar({ pct, tone = "coral", height = 8 }: { pct: number; tone?: "coral" | "moss" | "amber"; height?: number }) {
  const clamped = Math.max(0, Math.min(100, pct));
  const barColor = { coral: "bg-coral", moss: "bg-moss", amber: "bg-amber" }[tone];
  return (
    <div className="neu-inset w-full overflow-hidden rounded-full bg-bg-inset" style={{ height }}>
      <div
        className={clsx("h-full rounded-full transition-[width] duration-700 ease-out", barColor)}
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}
