import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, FileText, XCircle } from "lucide-react";
import { useState } from "react";
import { apiErrorMessage, calculateWoCarbon } from "../lib/api";
import { fmtInr, fmtNum, fmtTonnes, titleCase } from "../lib/format";
import type { FloorAreaBasis, WoCarbonResult } from "../lib/types";
import { useCompany } from "../lib/useCompany";
import { CategoryBreakdownChart } from "../charts/CategoryBreakdownChart";
import { Accordion } from "../components/ui/Accordion";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardLabel } from "../components/ui/Card";
import { Dropzone } from "../components/ui/Dropzone";
import { Field, Select, TextInput } from "../components/ui/Field";
import { ProgressBar } from "../components/ui/ProgressBar";
import { Spinner } from "../components/ui/Spinner";
import { StatTile } from "../components/ui/StatTile";
import { useToast } from "../components/ui/Toast";

export default function WoCalculator() {
  const { companyId } = useCompany();
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [floorArea, setFloorArea] = useState("");
  const [floorAreaBasis, setFloorAreaBasis] = useState<FloorAreaBasis | "">("");
  const [result, setResult] = useState<WoCarbonResult | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      calculateWoCarbon(file!, {
        floorAreaSqm: floorArea ? Number(floorArea) : undefined,
        floorAreaBasis: floorAreaBasis || undefined,
        companyId,
      }),
    onSuccess: (data) => {
      setResult(data);
      toast.success(`Parsed ${data.n_line_items_parsed.toLocaleString()} line items from the Work Order.`);
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="flex items-center gap-2.5 text-2xl text-ink">
          <FileText size={22} className="text-coral" /> Work Order carbon calculator
        </h1>
        <p className="mt-2 max-w-xl text-[13.5px] text-ink-soft">
          Self-contained PDF extraction — Rate/Amount read by the WO's own header-row position, not string-guessing.
          Same one emission-factor source as the BOQ engine.
        </p>
      </div>

      <Card>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-[1fr_200px_200px]">
          <Dropzone file={file} onFile={setFile} accept=".pdf" hint="A Work Order PDF with a detectable header row" />
          <Field label="Floor area (sqm)" hint="Optional">
            <TextInput type="number" min={0} value={floorArea} onChange={(e) => setFloorArea(e.target.value)} />
          </Field>
          <Field label="Floor area basis">
            <Select value={floorAreaBasis} onChange={(e) => setFloorAreaBasis(e.target.value as FloorAreaBasis | "")}>
              <option value="">—</option>
              <option value="net_internal_gia">Net internal GIA</option>
              <option value="built_up_total">Built-up total</option>
              <option value="carpet_saleable">Carpet / saleable</option>
              <option value="other">Other</option>
            </Select>
          </Field>
        </div>
        <div className="mt-4 flex justify-end">
          <Button onClick={() => mutation.mutate()} disabled={!file} loading={mutation.isPending} icon={<FileText size={15} />}>
            Calculate
          </Button>
        </div>
      </Card>

      {mutation.isPending && <Spinner label="Extracting text, locating the header row, computing every line… this can take a minute on a long PDF." />}

      {result && (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <StatTile label="Total carbon" value={fmtTonnes(result.total_gwp_kg_co2e)} tone="coral" />
            <StatTile label="Lines computed" value={`${result.n_line_items_computed.toLocaleString()}/${result.n_line_items_parsed.toLocaleString()}`} tone="moss" delay={0.05} />
            <StatTile label="Per sqm" value={result.gwp_per_sqm != null ? `${fmtNum(result.gwp_per_sqm, 0)} kg` : "—"} tone="coral" delay={0.1} />
            <StatTile
              label="Checksum"
              value={
                result.parse_checksum_ok == null ? (
                  "—"
                ) : result.parse_checksum_ok ? (
                  <CheckCircle2 size={22} className="text-moss" />
                ) : (
                  <XCircle size={22} className="text-rust" />
                )
              }
              tone={result.parse_checksum_ok ? "moss" : "amber"}
              delay={0.15}
            />
          </div>

          <Card>
            <CardLabel>WO amount vs. computed amount</CardLabel>
            <div className="flex items-center justify-between text-[13px]">
              <span className="text-ink-soft">Total WO amount</span>
              <span className="tabular text-ink">{fmtInr(result.total_wo_amount)}</span>
            </div>
            <div className="mt-1 flex items-center justify-between text-[13px]">
              <span className="text-ink-soft">Computed amount</span>
              <span className="tabular text-ink">{fmtInr(result.computed_wo_amount)}</span>
            </div>
          </Card>

          {result.coverage && (
            <Card>
              <CardLabel>Coverage</CardLabel>
              <ProgressBar pct={result.coverage.coverage_pct} tone={result.coverage.coverage_pct > 90 ? "moss" : "amber"} height={10} />
              <div className="mt-2 flex justify-between text-[11.5px] text-ink-faint">
                <span>{fmtInr(result.coverage.computed_value)} computed</span>
                <span>{fmtInr(result.coverage.total_value)} total WO value</span>
              </div>
              {result.coverage.excluded_by_reason.length > 0 && (
                <div className="mt-4 flex flex-col gap-2">
                  {result.coverage.excluded_by_reason.map((exc, i) => (
                    <div key={i} className="flex items-center justify-between rounded-lg border border-line bg-bg-raised/60 px-3 py-2 text-[12px]">
                      <span className="flex items-center gap-1.5 text-ink-soft">
                        <AlertTriangle size={12} className="text-amber" /> {titleCase(exc.reason)}
                      </span>
                      <span className="tabular text-ink-faint">
                        {exc.line_item_count} lines · {fmtInr(exc.value_excluded)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          )}

          <Card>
            <CardLabel>By category</CardLabel>
            <CategoryBreakdownChart categories={result.by_category} />
          </Card>

          {result.registered_as_reference != null && (
            <Accordion title="Reference registration" subtitle={result.registration_note ?? undefined}>
              <div className="flex items-center gap-2">
                <Badge tone={result.registered_as_reference ? "moss" : "neutral"}>
                  {result.registered_as_reference ? "Registered" : "Not registered"}
                </Badge>
                {result.reference_slug && <span className="font-mono text-[11px] text-ink-faint">{result.reference_slug}</span>}
              </div>
            </Accordion>
          )}
        </>
      )}
    </div>
  );
}
