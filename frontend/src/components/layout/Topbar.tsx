import { Building2, Wifi, WifiOff } from "lucide-react";
import { useEffect, useState } from "react";
import { health } from "../../lib/api";
import { useCompany } from "../../lib/useCompany";

export function Topbar() {
  const { companyId, setCompanyId } = useCompany();
  const [draft, setDraft] = useState(companyId);
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    let mounted = true;
    const check = () =>
      health()
        .then(() => mounted && setOnline(true))
        .catch(() => mounted && setOnline(false));
    check();
    const iv = setInterval(check, 20000);
    return () => {
      mounted = false;
      clearInterval(iv);
    };
  }, []);

  return (
    <header className="sticky top-0 z-20 flex h-16 items-center justify-between gap-3 border-b border-line bg-bg/85 px-4 backdrop-blur-md md:px-7">
      <div className="flex items-center gap-2 md:hidden">
        <div className="grid h-7 w-7 place-items-center rounded-lg bg-coral text-bg font-display text-sm">K</div>
      </div>

      <div className="flex items-center gap-2 rounded-full border border-line bg-bg-raised/70 px-1 py-1">
        <div className="flex items-center gap-1.5 pl-2.5 text-ink-faint">
          <Building2 size={13} />
        </div>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => setCompanyId(draft.trim() || "provident")}
          onKeyDown={(e) => e.key === "Enter" && (e.currentTarget as HTMLInputElement).blur()}
          spellCheck={false}
          className="w-28 bg-transparent font-mono text-[12px] text-ink outline-none placeholder:text-ink-faint sm:w-40"
          placeholder="company_id"
        />
      </div>

      <div className="flex items-center gap-2 text-[11px] text-ink-faint">
        <span className="hidden sm:inline">backend</span>
        {online === null ? (
          <span className="h-2 w-2 animate-pulse rounded-full bg-ink-faint" />
        ) : online ? (
          <span className="flex items-center gap-1 text-moss">
            <Wifi size={13} /> online
          </span>
        ) : (
          <span className="flex items-center gap-1 text-rust">
            <WifiOff size={13} /> unreachable
          </span>
        )}
      </div>
    </header>
  );
}
