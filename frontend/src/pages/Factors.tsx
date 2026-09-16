import { useQuery } from "@tanstack/react-query";
import { Database, History } from "lucide-react";
import { useState } from "react";
import { apiErrorMessage, getCurrentFactorSnapshot, getFactorCategoryHistory } from "../lib/api";
import { fmtDate } from "../lib/format";
import { Card, CardLabel } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { Spinner } from "../components/ui/Spinner";

export default function Factors() {
  const [selected, setSelected] = useState<string | null>(null);

  const snapshotQuery = useQuery({ queryKey: ["factors-current"], queryFn: () => getCurrentFactorSnapshot() });

  const historyQuery = useQuery({
    queryKey: ["factor-history", selected],
    queryFn: () => getFactorCategoryHistory(selected!),
    enabled: !!selected,
  });

  const categories = snapshotQuery.data ? Object.keys(snapshotQuery.data) : [];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="flex items-center gap-2.5 text-2xl text-ink">
          <Database size={22} className="text-coral" /> Emission factors
        </h1>
        <p className="mt-2 max-w-xl text-[13.5px] text-ink-soft">
          The live, current snapshot every calculation reads from — generated from the versioned factor history, so it
          can never drift from the source of truth. Pick a category to see every value it has ever held, and why.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[280px_minmax(0,1fr)]">
        <Card className="lg:sticky lg:top-20 lg:h-fit">
          <CardLabel>Categories</CardLabel>
          {snapshotQuery.isLoading && <Spinner label="Loading snapshot…" />}
          {snapshotQuery.error && <p className="text-[13px] text-amber">{apiErrorMessage(snapshotQuery.error)}</p>}
          <div className="flex max-h-[60vh] flex-col gap-0.5 overflow-y-auto">
            {categories.map((cat) => (
              <button
                key={cat}
                onClick={() => setSelected(cat)}
                className={`rounded-lg px-3 py-2 text-left font-mono text-[12px] transition-colors ${
                  selected === cat ? "bg-coral-soft text-coral" : "text-ink-soft hover:bg-white/[0.04] hover:text-ink"
                }`}
              >
                {cat}
              </button>
            ))}
          </div>
        </Card>

        <Card>
          {!selected ? (
            <EmptyState icon={<History size={26} />} title="Select a category" body="Its full changelog will show up here — oldest first." />
          ) : historyQuery.isLoading ? (
            <Spinner label="Loading history…" />
          ) : historyQuery.error ? (
            <p className="text-[13px] text-amber">{apiErrorMessage(historyQuery.error)}</p>
          ) : (
            <div>
              <CardLabel>{selected} — history</CardLabel>
              <div className="flex flex-col gap-3">
                {historyQuery.data?.map((entry, i) => (
                  <div key={i} className="rounded-xl border border-line bg-bg-raised/60 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2 text-[11.5px] text-ink-faint">
                      <span className="font-mono">
                        {fmtDate(entry.valid_from)} &rarr; {entry.valid_to ? fmtDate(entry.valid_to) : "current"}
                      </span>
                    </div>
                    <p className="mt-1.5 text-[13px] text-ink">{entry.changelog_note}</p>
                    <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-all rounded-lg bg-bg-inset px-3 py-2 font-mono text-[11px] text-ink-soft">
                      {JSON.stringify(entry.value, null, 2)}
                    </pre>
                  </div>
                ))}
              </div>
            </div>
          )}

          {!selected && snapshotQuery.data && (
            <pre className="mt-4 max-h-96 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] text-ink-soft">
              {JSON.stringify(snapshotQuery.data, null, 2).slice(0, 4000)}
            </pre>
          )}
        </Card>
      </div>
    </div>
  );
}
