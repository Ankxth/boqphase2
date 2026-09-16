import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, CalculatorIcon, FlaskConical } from "lucide-react";
import { useMemo, useState } from "react";
import { apiErrorMessage, calculateBoqCarbon, getSubstitutionCatalog, substituteBoqCarbon } from "../lib/api";
import { fmtInr, fmtKg, fmtNum, fmtPct, fmtTonnes, titleCase } from "../lib/format";
import type { BoqCarbonResult, BoqSubstitutionResponse, FloorAreaBasis } from "../lib/types";
import { useCompany } from "../lib/useCompany";
import { CategoryBreakdownChart } from "../charts/CategoryBreakdownChart";
import { Accordion } from "../components/ui/Accordion";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardLabel } from "../components/ui/Card";
import { Dropzone } from "../components/ui/Dropzone";
import { Field, Select, TextInput } from "../components/ui/Field";
import { ProgressBar } from "../components/ui/ProgressBar";
import { Slider } from "../components/ui/Slider";
import { Spinner } from "../components/ui/Spinner";
import { StatTile } from "../components/ui/StatTile";
import { Table, Td, Th, THead } from "../components/ui/Table";
import { useToast } from "../components/ui/Toast";

export default function BoqCalculator() {
  const { companyId } = useCompany();
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [floorArea, setFloorArea] = useState("");
  const [floorAreaBasis, setFloorAreaBasis] = useState<FloorAreaBasis | "">("");
  const [result, setResult] = useState<BoqCarbonResult | null>(null);
  const [rowsShown, setRowsShown] = useState(100);

  const calcMutation = useMutation({
    mutationFn: () =>
      calculateBoqCarbon(file!, {
        floorAreaSqm: floorArea ? Number(floorArea) : undefined,
        floorAreaBasis: floorAreaBasis || undefined,
        companyId,
      }),
    onSuccess: (data) => {
      setResult(data);
      setRowsShown(100);
      toast.success(`Computed ${data.n_lines_computed.toLocaleString()} of ${data.n_lines_total.toLocaleString()} line items.`);
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="flex items-center gap-2.5 text-2xl text-ink">
          <CalculatorIcon size={22} className="text-coral" /> BOQ carbon calculator
        </h1>
        <p className="mt-2 max-w-xl text-[13.5px] text-ink-soft">
          Upload a real Bill of Quantities. Every line the engine recognizes is classified, priced against one
          emission-factor source, and totalled — with honest coverage reporting for whatever it can't.
        </p>
      </div>

      <Card>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-[1fr_200px_200px]">
          <Dropzone file={file} onFile={setFile} accept=".xlsx,.xls" hint="Header-detecting parser, any BOQ shape" />
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
          <Button onClick={() => calcMutation.mutate()} disabled={!file} loading={calcMutation.isPending} icon={<CalculatorIcon size={15} />}>
            Calculate
          </Button>
        </div>
      </Card>

      {calcMutation.isPending && <Spinner label="Parsing, classifying, and computing every line…" />}

      {result && (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <StatTile label="Total carbon" value={fmtTonnes(result.total_gwp_kg_co2e)} tone="coral" />
            <StatTile label="Lines computed" value={`${result.n_lines_computed.toLocaleString()}/${result.n_lines_total.toLocaleString()}`} tone="moss" delay={0.05} />
            <StatTile label="Per sqm" value={result.gwp_per_sqm != null ? `${fmtNum(result.gwp_per_sqm, 0)} kg` : "—"} tone="coral" delay={0.1} />
            <StatTile label="Coverage" value={result.coverage ? fmtPct(result.coverage.coverage_pct) : "—"} tone="amber" delay={0.15} />
          </div>

          {result.coverage && (
            <Card>
              <CardLabel>Coverage — how much of the BOQ's real value this actually computed</CardLabel>
              <ProgressBar pct={result.coverage.coverage_pct} tone={result.coverage.coverage_pct > 90 ? "moss" : "amber"} height={10} />
              <div className="mt-2 flex justify-between text-[11.5px] text-ink-faint">
                <span>{fmtInr(result.coverage.computed_value)} computed</span>
                <span>{fmtInr(result.coverage.total_value)} total BOQ value</span>
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

          <Card>
            <div className="mb-3 flex items-center justify-between">
              <CardLabel>Line items</CardLabel>
              <span className="text-[11px] text-ink-faint">
                showing {Math.min(rowsShown, result.line_items.length)} of {result.line_items.length.toLocaleString()}
              </span>
            </div>
            <Table>
              <THead>
                <tr>
                  <Th>Description</Th>
                  <Th>Category</Th>
                  <Th align="right">Qty</Th>
                  <Th align="right">Carbon</Th>
                </tr>
              </THead>
              <tbody>
                {result.line_items.slice(0, rowsShown).map((li) => (
                  <tr key={li.row}>
                    <Td className="max-w-[280px] truncate" title={li.enriched_description}>
                      {li.enriched_description}
                    </Td>
                    <Td>{li.category ? <Badge tone="neutral">{titleCase(li.category)}</Badge> : <span className="text-ink-faint">{li.basis_note}</span>}</Td>
                    <Td align="right">
                      {li.qty != null ? fmtNum(li.qty, 1) : "—"} {li.uom ?? ""}
                    </Td>
                    <Td align="right">{li.gwp_kg_co2e != null ? fmtKg(li.gwp_kg_co2e) : "—"}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            {rowsShown < result.line_items.length && (
              <div className="mt-3 flex justify-center">
                <Button variant="secondary" size="sm" onClick={() => setRowsShown((n) => n + 200)}>
                  Show 200 more
                </Button>
              </div>
            )}
          </Card>

          <Accordion title="Scope & factor sourcing" subtitle="What this engine does and doesn't cover">
            <p className="mb-2">{result.scope_note}</p>
            <p>{result.factor_disclaimer}</p>
          </Accordion>

          <SubstitutionExplorer file={file!} floorArea={floorArea} floorAreaBasis={floorAreaBasis} baseTotal={result.total_gwp_kg_co2e} />
        </>
      )}
    </div>
  );
}

function SubstitutionExplorer({
  file,
  floorArea,
  floorAreaBasis,
  baseTotal,
}: {
  file: File;
  floorArea: string;
  floorAreaBasis: FloorAreaBasis | "";
  baseTotal: number;
}) {
  const toast = useToast();
  const catalogQuery = useQuery({ queryKey: ["substitution-catalog"], queryFn: getSubstitutionCatalog });
  const [pcts, setPcts] = useState<Record<string, number>>({});
  const [subResult, setSubResult] = useState<BoqSubstitutionResponse | null>(null);

  const activeCount = useMemo(() => Object.values(pcts).filter((v) => v > 0).length, [pcts]);

  const mutation = useMutation({
    mutationFn: () =>
      substituteBoqCarbon(
        file,
        Object.fromEntries(Object.entries(pcts).filter(([, v]) => v > 0)),
        { floorAreaSqm: floorArea ? Number(floorArea) : undefined, floorAreaBasis: floorAreaBasis || undefined }
      ),
    onSuccess: (data) => {
      setSubResult(data);
      toast.success("Substitution impact computed.");
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  if (catalogQuery.isLoading) return <Spinner label="Loading the substitution catalog…" />;
  if (!catalogQuery.data?.length) return null;

  return (
    <Card accent="moss">
      <CardLabel>What-if: material substitutions</CardLabel>
      <p className="mb-4 text-[12.5px] text-ink-soft">
        Dial in a substitution percentage for any material below, then recompute — every saving is a real re-run
        against your uploaded BOQ.
      </p>
      <div className="flex flex-col gap-5">
        {catalogQuery.data.map((entry) => (
          <div key={entry.substitution_id}>
            <Slider
              label={entry.label}
              value={pcts[entry.substitution_id] ?? 0}
              max={Math.max(entry.max_recommended_pct * 1.6, 20)}
              warnAbove={entry.max_recommended_pct}
              formatValue={(v) => `${v.toFixed(0)}%`}
              onChange={(v) => setPcts((p) => ({ ...p, [entry.substitution_id]: v }))}
            />
            <p className="mt-1.5 text-[11px] leading-relaxed text-ink-faint">{entry.reasoning}</p>
          </div>
        ))}
      </div>
      <div className="mt-5 flex justify-end">
        <Button onClick={() => mutation.mutate()} disabled={activeCount === 0} loading={mutation.isPending} icon={<FlaskConical size={15} />}>
          Recompute with {activeCount || "no"} substitution{activeCount === 1 ? "" : "s"}
        </Button>
      </div>

      {subResult && (
        <div className="mt-5 flex flex-col gap-3 border-t border-line pt-4">
          {subResult.combined_impact && (
            <div className="flex flex-wrap items-center gap-3">
              <span className="font-display text-2xl text-ink tabular">{fmtKg(baseTotal)}</span>
              <ArrowRight size={16} className="text-ink-faint" />
              <span className="font-display text-2xl text-moss tabular">
                {fmtKg(baseTotal - subResult.combined_impact.total_savings_kg_co2e)}
              </span>
              <Badge tone="moss">−{fmtPct(subResult.combined_impact.total_savings_pct_of_total_boq)} of total BOQ</Badge>
              {subResult.combined_impact.requires_engineering_review && <Badge tone="amber">needs engineering review</Badge>}
            </div>
          )}
          {subResult.substitutions.map((s) => (
            <div key={s.substitution_id} className="flex items-center justify-between rounded-lg border border-line bg-bg-raised/60 px-3.5 py-2.5 text-[12.5px]">
              <span className="text-ink">{s.label}</span>
              <span className="flex items-center gap-2">
                <span className="text-ink-faint">{s.user_pct}%</span>
                <span className="text-moss tabular">−{fmtKg(s.savings_kg_co2e)}</span>
                {s.exceeds_recommended && <Badge tone="amber">over recommended</Badge>}
              </span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
