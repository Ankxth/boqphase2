import clsx from "clsx";
import { Database, FileSpreadsheet, FileText, Flame, LayoutGrid, SlidersHorizontal } from "lucide-react";
import { NavLink } from "react-router-dom";

const NAV = [
  { to: "/", label: "Projects", icon: LayoutGrid, end: true },
  { to: "/tools/boq", label: "BOQ Calculator", icon: FileSpreadsheet },
  { to: "/tools/wo", label: "Work Order Calculator", icon: FileText },
  { to: "/onboarding", label: "Onboarding", icon: SlidersHorizontal },
  { to: "/factors", label: "Emission Factors", icon: Database },
];

export function Sidebar() {
  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-[228px] flex-col border-r border-line bg-bg-raised/60 px-3.5 py-5 backdrop-blur-sm md:flex">
      <div className="mb-8 flex items-center gap-2.5 px-2">
        <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-coral to-rust text-bg">
          <Flame size={17} strokeWidth={2.3} />
        </div>
        <div>
          <div className="font-display text-[15px] leading-none text-ink">Kiln</div>
          <div className="mt-0.5 font-mono text-[9px] uppercase tracking-[0.14em] text-ink-faint">carbon intelligence</div>
        </div>
      </div>

      <nav className="flex flex-1 flex-col gap-1">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              clsx(
                "flex items-center gap-2.5 rounded-xl px-3 py-2.5 text-[13px] font-medium transition-colors",
                isActive ? "bg-coral-soft text-coral" : "text-ink-soft hover:bg-white/[0.04] hover:text-ink"
              )
            }
          >
            <item.icon size={16} strokeWidth={2} />
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="rounded-xl border border-line bg-bg-card/60 px-3 py-3">
        <div className="font-mono text-[9.5px] uppercase tracking-[0.1em] text-ink-faint">Workstreams shipped</div>
        <div className="mt-1 font-display text-lg text-moss">00 – 13</div>
        <div className="mt-0.5 text-[10.5px] text-ink-faint">Foundation Plan closed out</div>
      </div>
    </aside>
  );
}
