import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarPlus, GaugeCircle, Landmark, Sparkles, UploadCloud } from "lucide-react";
import { useState } from "react";
import { apiErrorMessage, getDashboard, listBills, recordBaseline, uploadBill } from "../../lib/api";
import { fmtDate, fmtKg, fmtNum, fmtPct, titleCase } from "../../lib/format";
import type { BaselineSourceType, FloorAreaBasis } from "../../lib/types";
import { useCompany } from "../../lib/useCompany";
import { RunningCarbonChart } from "../../charts/RunningCarbonChart";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card, CardLabel } from "../../components/ui/Card";
import { Dropzone } from "../../components/ui/Dropzone";
import { EmptyState } from "../../components/ui/EmptyState";
import { Field, Select, TextInput } from "../../components/ui/Field";
import { Spinner } from "../../components/ui/Spinner";
import { StatTile } from "../../components/ui/StatTile";
import { Table, Td, Th, THead } from "../../components/ui/Table";
import { useToast } from "../../components/ui/Toast";

export default function Phase3Tab({ projectId }: { projectId: string }) {
  const { companyId } = useCompany();
  const qc = useQueryClient();
  const toast = useToast();

  const dashboardQuery = useQuery({
    queryKey: ["dashboard", companyId, projectId],
    queryFn: () => getDashboard(projectId, companyId),
    retry: false,
  });

  const billsQuery = useQuery({
    queryKey: ["bills", companyId, projectId],
    queryFn: () => listBills(projectId, companyId),
  });

  const hasBaseline = !!dashboardQuery.data;
  const noBaselineYet = dashboardQuery.isError;

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["dashboard", companyId, projectId] });
    qc.invalidateQueries({ queryKey: ["bills", companyId, projectId] });
    qc.invalidateQueries({ queryKey: ["projects", companyId] });
  };

  // ---- baseline form state ----
  const [sourceType, setSourceType] = useState<BaselineSourceType>("phase1_estimate");
  const [baselineFile, setBaselineFile] = useState<File | null>(null);
  const [floorArea, setFloorArea] = useState<string>("");
  const [floorAreaBasis, setFloorAreaBasis] = useState<FloorAreaBasis | "">("");
  const [overwriteBaseline, setOverwriteBaseline] = useState(false);

  const baselineMutation = useMutation({
    mutationFn: () =>
      recordBaseline(projectId, sourceType, {
        file: baselineFile ?? undefined,
        floorAreaSqm: floorArea ? Number(floorArea) : undefined,
        floorAreaBasis: floorAreaBasis || undefined,
        companyId,
        overwrite: overwriteBaseline,
      }),
    onSuccess: () => {
      toast.success("Baseline recorded.");
      invalidate();
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  // ---- bill form state ----
  const [period, setPeriod] = useState("");
  const [billedDate, setBilledDate] = useState("");
  const [billFile, setBillFile] = useState<File | null>(null);
  const [statedPct, setStatedPct] = useState("");

  const billMutation = useMutation({
    mutationFn: () =>
      uploadBill(projectId, period, billedDate, billFile!, {
        statedPercentComplete: statedPct ? Number(statedPct) : undefined,
        companyId,
      }),
    onSuccess: () => {
      toast.success(`Bill for ${period} recorded.`);
      setPeriod("");
      setBilledDate("");
      setBillFile(null);
      setStatedPct("");
      invalidate();
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  return (
    <div className="flex flex-col gap-6">
      {dashboardQuery.isLoading && <Spinner label="Checking for a recorded baseline…" />}

      {noBaselineYet && (
        <Card accent="amber">
          <CardLabel>Record a baseline first</CardLabel>
          <p className="mb-4 max-w-xl text-[13px] text-ink-soft">
            Every bill uploaded afterward is compared against this baseline, never against another bill. No real
            BOQ/Work Order yet? Choose <span className="text-amber">Phase 1 estimate</span> — it reuses this project's
            own concept-stage calculation as a running estimate, clearly flagged as such everywhere it's shown.
          </p>
          <BaselineForm
            sourceType={sourceType}
            setSourceType={setSourceType}
            baselineFile={baselineFile}
            setBaselineFile={setBaselineFile}
            floorArea={floorArea}
            setFloorArea={setFloorArea}
            floorAreaBasis={floorAreaBasis}
            setFloorAreaBasis={setFloorAreaBasis}
            overwrite={overwriteBaseline}
            setOverwrite={setOverwriteBaseline}
            onSubmit={() => baselineMutation.mutate()}
            loading={baselineMutation.isPending}
          />
        </Card>
      )}

      {hasBaseline && dashboardQuery.data && (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <StatTile
              label="Baseline"
              value={fmtKg(dashboardQuery.data.baseline.total_gwp_kg_co2e)}
              sub={dashboardQuery.data.baseline.is_estimated ? "Phase 1-estimated" : titleCase(dashboardQuery.data.baseline.source_type)}
              icon={<Landmark size={15} />}
              tone={dashboardQuery.data.baseline.is_estimated ? "amber" : "moss"}
            />
            <StatTile
              label="Billed to date"
              value={fmtKg(dashboardQuery.data.billed_to_date_gwp_kg_co2e)}
              sub={dashboardQuery.data.latest_period ? `as of ${dashboardQuery.data.latest_period}` : "no bills yet"}
              icon={<CalendarPlus size={15} />}
              tone="coral"
              delay={0.05}
            />
            <StatTile
              label="% complete"
              value={dashboardQuery.data.percent_complete != null ? fmtPct(dashboardQuery.data.percent_complete) : "—"}
              sub={dashboardQuery.data.percent_complete_source ? titleCase(dashboardQuery.data.percent_complete_source) : undefined}
              icon={<GaugeCircle size={15} />}
              tone="coral"
              delay={0.1}
            />
            <StatTile
              label="Projected total"
              value={dashboardQuery.data.projected_total_gwp_kg_co2e != null ? fmtKg(dashboardQuery.data.projected_total_gwp_kg_co2e) : "—"}
              sub={dashboardQuery.data.projected_vs_baseline_pct != null ? `${fmtPct(dashboardQuery.data.projected_vs_baseline_pct)} vs baseline` : undefined}
              icon={<Sparkles size={15} />}
              tone="amber"
              delay={0.15}
            />
          </div>

          {dashboardQuery.data.notes.length > 0 && (
            <Card accent="amber">
              {dashboardQuery.data.notes.map((n, i) => (
                <p key={i} className="text-[12.5px] leading-relaxed text-ink-soft last:mb-0">
                  {n}
                </p>
              ))}
            </Card>
          )}

          <Card>
            <CardLabel>Running carbon vs. baseline</CardLabel>
            {dashboardQuery.data.points.length === 0 ? (
              <EmptyState title="No bills recorded yet" body="Upload the first bill below to start the running-carbon chart." />
            ) : (
              <RunningCarbonChart
                points={dashboardQuery.data.points}
                baselineTotal={dashboardQuery.data.baseline.total_gwp_kg_co2e}
                projectedTotal={dashboardQuery.data.projected_total_gwp_kg_co2e}
              />
            )}
          </Card>

          {dashboardQuery.data.benchmark_available && (
            <Card accent="moss">
              <CardLabel>Projected vs. a typical building</CardLabel>
              <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
                <div>
                  <div className="font-display text-2xl text-ink tabular">{fmtNum(dashboardQuery.data.projected_carbon_per_sqm, 0)}</div>
                  <div className="text-[11px] text-ink-faint">projected (kg/sqm)</div>
                </div>
                <div>
                  <div className="font-display text-2xl text-ink-soft tabular">{fmtNum(dashboardQuery.data.typical_carbon_per_sqm, 0)}</div>
                  <div className="text-[11px] text-ink-faint">typical (kg/sqm)</div>
                </div>
                {dashboardQuery.data.pct_difference_from_typical != null && (
                  <Badge tone={dashboardQuery.data.pct_difference_from_typical > 0 ? "amber" : "moss"}>
                    {fmtPct(dashboardQuery.data.pct_difference_from_typical)} vs typical
                  </Badge>
                )}
              </div>
            </Card>
          )}
        </>
      )}

      {/* ---- bills ---- */}
      <Card>
        <CardLabel>Record a bill</CardLabel>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Period" hint="e.g. 2026-Q3 -- also its storage id">
            <TextInput value={period} onChange={(e) => setPeriod(e.target.value)} placeholder="2026-Q3" />
          </Field>
          <Field label="Billed as-of date">
            <TextInput type="date" value={billedDate} onChange={(e) => setBilledDate(e.target.value)} />
          </Field>
          <Field label="Stated % complete" hint="Optional -- overrides the derived figure">
            <TextInput type="number" min={0} max={100} value={statedPct} onChange={(e) => setStatedPct(e.target.value)} />
          </Field>
        </div>
        <div className="mt-4">
          <Dropzone file={billFile} onFile={setBillFile} accept=".xlsx,.xls" label="Bill Excel file (quantities-to-date)" />
        </div>
        <div className="mt-4 flex justify-end">
          <Button
            onClick={() => billMutation.mutate()}
            disabled={!period || !billedDate || !billFile}
            loading={billMutation.isPending}
            icon={<UploadCloud size={15} />}
          >
            Record bill
          </Button>
        </div>
      </Card>

      {(billsQuery.data?.length ?? 0) > 0 && (
        <Card>
          <CardLabel>Bill history</CardLabel>
          <Table>
            <THead>
              <tr>
                <Th>Period</Th>
                <Th>Billed as of</Th>
                <Th align="right">To-date carbon</Th>
                <Th align="right">To-date value</Th>
                <Th align="right">% complete</Th>
              </tr>
            </THead>
            <tbody>
              {billsQuery.data!.map((b) => (
                <tr key={b.period}>
                  <Td>{b.period}</Td>
                  <Td>{fmtDate(b.billed_date)}</Td>
                  <Td align="right">{fmtKg(b.total_gwp_kg_co2e_to_date)}</Td>
                  <Td align="right">{fmtNum(b.total_value_to_date, 0)}</Td>
                  <Td align="right">{b.stated_percent_complete != null ? fmtPct(b.stated_percent_complete) : "—"}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}

      {hasBaseline && (
        <Card>
          <CardLabel>Replace the baseline</CardLabel>
          <p className="mb-4 text-[12.5px] text-ink-soft">
            Swap the estimated baseline for a real one once a BOQ/Work Order exists, or re-record after a scope change.
            Requires the overwrite switch below.
          </p>
          <BaselineForm
            sourceType={sourceType}
            setSourceType={setSourceType}
            baselineFile={baselineFile}
            setBaselineFile={setBaselineFile}
            floorArea={floorArea}
            setFloorArea={setFloorArea}
            floorAreaBasis={floorAreaBasis}
            setFloorAreaBasis={setFloorAreaBasis}
            overwrite={overwriteBaseline}
            setOverwrite={setOverwriteBaseline}
            onSubmit={() => baselineMutation.mutate()}
            loading={baselineMutation.isPending}
          />
        </Card>
      )}
    </div>
  );
}

function BaselineForm({
  sourceType,
  setSourceType,
  baselineFile,
  setBaselineFile,
  floorArea,
  setFloorArea,
  floorAreaBasis,
  setFloorAreaBasis,
  overwrite,
  setOverwrite,
  onSubmit,
  loading,
}: {
  sourceType: BaselineSourceType;
  setSourceType: (s: BaselineSourceType) => void;
  baselineFile: File | null;
  setBaselineFile: (f: File | null) => void;
  floorArea: string;
  setFloorArea: (v: string) => void;
  floorAreaBasis: FloorAreaBasis | "";
  setFloorAreaBasis: (v: FloorAreaBasis | "") => void;
  overwrite: boolean;
  setOverwrite: (v: boolean) => void;
  onSubmit: () => void;
  loading: boolean;
}) {
  const needsFile = sourceType !== "phase1_estimate";
  return (
    <div className="flex flex-col gap-4">
      <Field label="Source">
        <Select value={sourceType} onChange={(e) => setSourceType(e.target.value as BaselineSourceType)}>
          <option value="phase1_estimate">Phase 1 estimate (no file needed)</option>
          <option value="boq">Bill of Quantities (.xlsx)</option>
          <option value="wo">Work Order (.pdf)</option>
        </Select>
      </Field>
      {needsFile && (
        <Dropzone
          file={baselineFile}
          onFile={setBaselineFile}
          accept={sourceType === "boq" ? ".xlsx,.xls" : ".pdf"}
          label={sourceType === "boq" ? "Upload the BOQ Excel file" : "Upload the Work Order PDF"}
        />
      )}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Floor area (sqm)" hint="Optional -- unlocks the typical-building comparison">
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
      <label className="flex items-center gap-2 text-[12.5px] text-ink-soft">
        <input type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} className="accent-coral" />
        Overwrite an existing baseline
      </label>
      <div className="flex justify-end">
        <Button onClick={onSubmit} disabled={needsFile && !baselineFile} loading={loading} icon={<Landmark size={15} />}>
          Record baseline
        </Button>
      </div>
    </div>
  );
}
