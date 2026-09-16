import { useMutation, useQuery } from "@tanstack/react-query";
import { BadgeCheck, ListChecks, Tags, UploadCloud } from "lucide-react";
import { useMemo, useState } from "react";
import {
  apiErrorMessage,
  confirmOnboardingJob,
  getOnboardingJob,
  listCanonicalCategories,
  uploadItemCodes,
  type ConfirmDecision,
} from "../lib/api";
import { useCompany } from "../lib/useCompany";
import { Accordion } from "../components/ui/Accordion";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardLabel } from "../components/ui/Card";
import { Dropzone } from "../components/ui/Dropzone";
import { EmptyState } from "../components/ui/EmptyState";
import { Spinner } from "../components/ui/Spinner";
import { Table, Td, Th, THead } from "../components/ui/Table";
import { useToast } from "../components/ui/Toast";

// The onboarding job/review-queue/canonical-category response shapes are
// intentionally untyped on the backend (raw dict responses in the
// OpenAPI spec), so this page introspects rather than assuming field
// names -- it renders whatever comes back instead of guessing wrong and
// silently dropping data the backend actually sent.

function firstArrayField(obj: Record<string, unknown>): { key: string; items: Record<string, unknown>[] } | null {
  for (const [k, v] of Object.entries(obj)) {
    if (Array.isArray(v) && v.length > 0 && typeof v[0] === "object") {
      return { key: k, items: v as Record<string, unknown>[] };
    }
  }
  return null;
}

function scalarEntries(obj: Record<string, unknown>): [string, unknown][] {
  return Object.entries(obj).filter(([, v]) => typeof v !== "object" || v === null);
}

export default function Onboarding() {
  const { companyId } = useCompany();
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [useLlm, setUseLlm] = useState(true);
  const [job, setJob] = useState<Record<string, unknown> | null>(null);
  const [decisions, setDecisions] = useState<Record<string, "accept" | "skip">>({});

  const uploadMutation = useMutation({
    mutationFn: () => uploadItemCodes(companyId, file!, useLlm),
    onSuccess: (data) => {
      setJob(data as Record<string, unknown>);
      setDecisions({});
      toast.success("Upload processed — review the queue below.");
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  const jobId = job?.job_id as string | undefined;

  const refreshMutation = useMutation({
    mutationFn: () => getOnboardingJob(companyId, jobId!),
    onSuccess: (data) => {
      setJob(data as Record<string, unknown>);
      toast.info("Job status refreshed.");
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  const queue = job ? firstArrayField(job) : null;

  const confirmMutation = useMutation({
    mutationFn: () => {
      const decisionsPayload: ConfirmDecision[] = (queue?.items ?? [])
        .filter((item) => {
          const code = String(item.code ?? item.id ?? "");
          return code && decisions[code] === "accept";
        })
        .map((item) => ({ code: String(item.code ?? item.id) }));
      return confirmOnboardingJob(companyId, jobId!, decisionsPayload);
    },
    onSuccess: () => toast.success("Decisions confirmed and written to this company's dataset."),
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  const acceptedCount = useMemo(() => Object.values(decisions).filter((d) => d === "accept").length, [decisions]);

  const categoriesQuery = useQuery({ queryKey: ["canonical-categories"], queryFn: listCanonicalCategories });
  const categoryList = Array.isArray(categoriesQuery.data)
    ? (categoriesQuery.data as Record<string, unknown>[])
    : categoriesQuery.data && typeof categoriesQuery.data === "object"
      ? Object.entries(categoriesQuery.data as Record<string, unknown>).map(([k, v]) => ({ category: k, ...(typeof v === "object" && v ? v : { value: v }) }))
      : [];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="flex items-center gap-2.5 text-2xl text-ink">
          <UploadCloud size={22} className="text-coral" /> Company onboarding
        </h1>
        <p className="mt-2 max-w-xl text-[13.5px] text-ink-soft">
          Upload {companyId}'s own item-code dataset — a cheap regex pass classifies what it can, an LLM drafts the
          rest against a closed vocabulary, and nothing is written to the shared master file until you confirm it.
        </p>
      </div>

      <Card>
        <CardLabel>Upload item codes</CardLabel>
        <Dropzone file={file} onFile={setFile} accept=".xlsx,.xls,.csv" hint="Any item-code export with a detectable header row" />
        <label className="mt-4 flex items-center gap-2 text-[12.5px] text-ink-soft">
          <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} className="accent-coral" />
          Use an LLM draft for whatever the regex pass can't classify
        </label>
        <div className="mt-4 flex justify-end">
          <Button onClick={() => uploadMutation.mutate()} disabled={!file} loading={uploadMutation.isPending} icon={<UploadCloud size={15} />}>
            Upload &amp; classify
          </Button>
        </div>
      </Card>

      {job && (
        <Card accent="moss">
          <div className="mb-3 flex items-center justify-between">
            <CardLabel>Onboarding job</CardLabel>
            {jobId && (
              <Button size="sm" variant="ghost" loading={refreshMutation.isPending} onClick={() => refreshMutation.mutate()}>
                Refresh status
              </Button>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            {scalarEntries(job).map(([k, v]) => (
              <Badge key={k} tone="neutral" className="normal-case tracking-normal">
                {k.replace(/_/g, " ")}: {String(v)}
              </Badge>
            ))}
          </div>

          {queue ? (
            <div className="mt-5">
              <div className="mb-2 flex items-center justify-between">
                <span className="flex items-center gap-1.5 text-[12.5px] text-ink-soft">
                  <ListChecks size={14} /> Review queue ({queue.items.length})
                </span>
                <span className="text-[11px] text-ink-faint">{acceptedCount} accepted</span>
              </div>
              <Table>
                <THead>
                  <tr>
                    <Th>Item</Th>
                    <Th align="right">Decision</Th>
                  </tr>
                </THead>
                <tbody>
                  {queue.items.map((item, i) => {
                    const code = String(item.code ?? item.id ?? i);
                    return (
                      <tr key={code}>
                        <Td>
                          <div className="flex flex-wrap gap-1.5">
                            {scalarEntries(item).map(([k, v]) => (
                              <span key={k} className="text-[11.5px] text-ink-soft">
                                <span className="text-ink-faint">{k}:</span> {String(v)}
                              </span>
                            ))}
                          </div>
                        </Td>
                        <Td align="right">
                          <div className="flex justify-end gap-1.5">
                            <button
                              onClick={() => setDecisions((d) => ({ ...d, [code]: "accept" }))}
                              className={`rounded-full px-2.5 py-1 text-[11px] ${decisions[code] === "accept" ? "bg-moss-soft text-moss" : "bg-white/5 text-ink-faint hover:text-ink"}`}
                            >
                              accept
                            </button>
                            <button
                              onClick={() => setDecisions((d) => ({ ...d, [code]: "skip" }))}
                              className={`rounded-full px-2.5 py-1 text-[11px] ${decisions[code] === "skip" ? "bg-rust-soft text-rust" : "bg-white/5 text-ink-faint hover:text-ink"}`}
                            >
                              skip
                            </button>
                          </div>
                        </Td>
                      </tr>
                    );
                  })}
                </tbody>
              </Table>
              <div className="mt-4 flex justify-end">
                <Button onClick={() => confirmMutation.mutate()} disabled={acceptedCount === 0} loading={confirmMutation.isPending} icon={<BadgeCheck size={15} />}>
                  Confirm {acceptedCount} decision{acceptedCount === 1 ? "" : "s"}
                </Button>
              </div>
            </div>
          ) : (
            <Accordion title="Raw job payload" subtitle="No recognizable review-queue array in this response">
              <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px]">{JSON.stringify(job, null, 2)}</pre>
            </Accordion>
          )}
        </Card>
      )}

      <Card>
        <div className="mb-3 flex items-center gap-1.5">
          <Tags size={14} className="text-ink-faint" />
          <CardLabel>Canonical categories — shared across every company</CardLabel>
        </div>
        {categoriesQuery.isLoading ? (
          <Spinner label="Loading…" />
        ) : categoryList.length === 0 ? (
          <EmptyState title="No canonical categories returned" />
        ) : (
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {categoryList.map((c, i) => (
              <div key={i} className="rounded-lg border border-line bg-bg-raised/60 px-3 py-2.5 text-[12px]">
                {scalarEntries(c).map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-2 text-ink-soft">
                    <span className="text-ink-faint">{k}</span>
                    <span className="truncate text-ink">{String(v)}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
