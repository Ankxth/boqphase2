import clsx from "clsx";
import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
  loading?: boolean;
  icon?: ReactNode;
  children?: ReactNode;
}

const VARIANTS: Record<string, string> = {
  primary: "bg-coral text-bg font-semibold hover:bg-[#ff7d54] active:scale-[0.98]",
  secondary: "bg-bg-raised text-ink border border-line hover:border-line-strong neu-pill",
  ghost: "bg-transparent text-ink-soft hover:text-ink hover:bg-white/[0.04]",
  danger: "bg-rust/15 text-rust border border-rust/30 hover:bg-rust/25",
};

const SIZES: Record<string, string> = {
  sm: "px-3 py-1.5 text-[12.5px] rounded-full gap-1.5",
  md: "px-4.5 py-2.5 text-[13.5px] rounded-full gap-2",
  lg: "px-6 py-3.5 text-[15px] rounded-full gap-2.5",
};

export function Button({
  variant = "primary",
  size = "md",
  loading,
  icon,
  disabled,
  className,
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={clsx(
        "inline-flex items-center justify-center whitespace-nowrap font-sans transition-all duration-150 disabled:cursor-not-allowed disabled:opacity-45",
        VARIANTS[variant],
        SIZES[size],
        className
      )}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <Loader2 size={15} className="animate-spin" /> : icon}
      {children}
    </button>
  );
}
