import clsx from "clsx";
import { Database, FileSpreadsheet, FileText, LayoutGrid, SlidersHorizontal } from "lucide-react";
import { NavLink } from "react-router-dom";

const NAV = [
  { to: "/", label: "Projects", icon: LayoutGrid, end: true },
  { to: "/tools/boq", label: "BOQ", icon: FileSpreadsheet },
  { to: "/tools/wo", label: "WO", icon: FileText },
  { to: "/onboarding", label: "Onboard", icon: SlidersHorizontal },
  { to: "/factors", label: "Factors", icon: Database },
];

export function MobileNav() {
  return (
    <nav className="fixed inset-x-0 bottom-0 z-30 flex items-stretch justify-around border-t border-line bg-bg-raised/95 backdrop-blur-md md:hidden">
      {NAV.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) =>
            clsx(
              "flex flex-1 flex-col items-center gap-0.5 py-2.5 text-[10px] font-medium",
              isActive ? "text-coral" : "text-ink-faint"
            )
          }
        >
          <item.icon size={17} />
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}
