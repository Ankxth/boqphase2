import { useId } from "react";

export function Slider({
  label,
  value,
  min = 0,
  max = 100,
  step = 1,
  onChange,
  formatValue,
  warnAbove,
  disabled,
}: {
  label: string;
  value: number;
  min?: number;
  max?: number;
  step?: number;
  onChange: (v: number) => void;
  formatValue?: (v: number) => string;
  warnAbove?: number;
  disabled?: boolean;
}) {
  const id = useId();
  const pct = ((value - min) / (max - min)) * 100;
  const isOverWarn = warnAbove != null && value > warnAbove;

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <label htmlFor={id} className="text-[13px] text-ink-soft">
          {label}
        </label>
        <span className={`font-mono text-[13px] tabular ${isOverWarn ? "text-amber" : "text-ink"}`}>
          {formatValue ? formatValue(value) : value}
        </span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="slider-track w-full disabled:opacity-40"
        style={{
          background: `linear-gradient(to right, ${isOverWarn ? "#e8a94b" : "#ff6a3d"} ${pct}%, rgba(255,255,255,0.08) ${pct}%)`,
        }}
      />
      {warnAbove != null && (
        <div className="mt-1 text-[10.5px] font-mono uppercase tracking-wide text-ink-faint">
          recommended max {formatValue ? formatValue(warnAbove) : warnAbove}
        </div>
      )}
    </div>
  );
}
