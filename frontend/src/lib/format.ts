export function fmtKg(kg: number | null | undefined, digits = 0): string {
  if (kg == null || Number.isNaN(kg)) return "—";
  return `${kg.toLocaleString("en-IN", { maximumFractionDigits: digits })} kgCO2e`;
}

export function fmtTonnes(kg: number | null | undefined, digits = 1): string {
  if (kg == null || Number.isNaN(kg)) return "—";
  return `${(kg / 1000).toLocaleString("en-IN", { maximumFractionDigits: digits })} t CO2e`;
}

export function fmtNum(n: number | null | undefined, digits = 0): string {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString("en-IN", { maximumFractionDigits: digits });
}

export function fmtPct(n: number | null | undefined, digits = 1): string {
  if (n == null || Number.isNaN(n)) return "—";
  return `${n.toLocaleString("en-IN", { maximumFractionDigits: digits })}%`;
}

export function fmtInr(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  if (Math.abs(n) >= 10000000) return `₹${(n / 10000000).toLocaleString("en-IN", { maximumFractionDigits: 2 })} Cr`;
  if (Math.abs(n) >= 100000) return `₹${(n / 100000).toLocaleString("en-IN", { maximumFractionDigits: 2 })} L`;
  return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

export function titleCase(s: string | null | undefined): string {
  if (!s) return "—";
  return s
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("en-IN", { year: "numeric", month: "short", day: "numeric" });
  } catch {
    return iso;
  }
}
