import type { ReactNode, SelectHTMLAttributes, InputHTMLAttributes } from "react";
import { useId } from "react";

export function Field({ label, hint, children, badge }: { label: string; hint?: string; children: ReactNode; badge?: ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <label className="text-[12.5px] font-medium text-ink-soft">{label}</label>
        {badge}
      </div>
      {children}
      {hint && <div className="mt-1 text-[11px] text-ink-faint">{hint}</div>}
    </div>
  );
}

export function TextInput(props: InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  return (
    <input
      id={id}
      {...props}
      className={
        "neu-inset w-full rounded-lg border border-line bg-bg-inset px-3.5 py-2.5 text-[13.5px] text-ink outline-none placeholder:text-ink-faint focus:border-coral/60 " +
        (props.className ?? "")
      }
    />
  );
}

export function Select({ children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={
        "neu-inset w-full appearance-none rounded-lg border border-line bg-bg-inset bg-[right_0.9rem_center] bg-no-repeat px-3.5 py-2.5 text-[13.5px] text-ink outline-none focus:border-coral/60 " +
        (props.className ?? "")
      }
      style={{
        backgroundImage:
          "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%236e6c5e' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E\")",
      }}
    >
      {children}
    </select>
  );
}
