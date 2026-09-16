import { useQuery } from "@tanstack/react-query";
import { Award, Flame, IndianRupee, TrendingUp } from "lucide-react";
import { apiErrorMessage, calculateProject } from "../../lib/api";
import { fmtInr, fmtKg, fmtNum, fmtPct, fmtTonnes, titleCase } from "../../lib/format";
import type { FieldValue, ProjectSchema } from "../../lib/types";
import { useCompany } from "../../lib/useCompany";
import { Badge, SourceBadge } from "../../components/ui/Badge";
import { Card, CardLabel } from "../../components/ui/Card";
import { Spinner } from "../../components/ui/Spinner";
import { StatTile } from "../../components/ui/StatTile";
import { Table, Td, Th, THead } from "../../components/ui/Table";

function FieldRow({ label, fv, unit }: { label: string; fv: FieldValue<unknown>; unit?: string }) {
  const display = fv.value == null ? "—" : typeof fv.value === "string" ? titleCase(fv.value) : `${fv.value}${unit ?? ""}`;
  return (
    <div className="flex items-center justify-between gap-3 border-b border-line py-2.5 last:border-none">
      <span className="text-[12.5px] text-ink-soft">{label}</span>
      <div className="flex items-center gap-2">
        <span className="text-[13px] text-ink">{display}</span>
        <SourceBadge source={fv.source} confidence={fv.confidence} />
      </div>
    </div>
  );
}

export default function OverviewTab({ project }: { project: ProjectSchema }) {
  const { companyId } = useCompany();
  const { data, isLoading, error } = useQuery({
    queryKey: ["calculate", companyId, project.project_id],
    queryFn: () => calculateProject(project.project_id, companyId),
  });

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="flex flex-col gap-5">
        {isLoading && <Spinner label="Running the calculation engine…" />}

        {error && (
          <Card accent="amber">
            <p className="text-[13px] text-amber">{apiErrorMessage(error)}</p>
          </Card>
        )}

        {data && (
          <>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <StatTile label="Total carbon" value={fmtTonnes(data.carbon.total_carbon_kg)} icon={<Flame size={15} />} tone="coral" />
              <StatTile label="Per sqm" value={`${fmtNum(data.carbon.carbon_per_sqm, 0)} kg`} icon={<TrendingUp size={15} />} tone="coral" delay={0.05} />
              <StatTile label="Est. cost" value={fmtInr(data.cost.total_cost_inr)} icon={<IndianRupee size={15} />} tone="moss" delay={0.1} />
              <StatTile label="GRIHA C21" value={`${data.griha_criterion_21.points_estimated}/${data.griha_criterion_21.max_points}`} icon={<Award size={15} />} tone="amber" delay={0.15} />
            </div>

            <Card>
              <CardLabel>Carbon breakdown</CardLabel>
              <Table>
                <THead>
                  <tr>
                    <Th>Material</Th>
                    <Th align="right">Quantity</Th>
                    <Th align="right">Factor</Th>
                    <Th align="right">Carbon</Th>
                  </tr>
                </THead>
                <tbody>
                  {data.carbon.breakdown.map((b, i) => (
                    <tr key={i}>
                      <Td>{b.material}</Td>
                      <Td align="right">
                        {fmtNum(b.quantity, 1)} {b.quantity_unit}
                      </Td>
                      <Td align="right">
                        {b.factor_used} {b.factor_unit}
                      </Td>
                      <Td align="right">{fmtKg(b.carbon_kg)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              <p className="mt-3 text-[11.5px] leading-relaxed text-ink-faint">{data.carbon.scope_note}</p>
            </Card>

            <Card accent="moss">
              <CardLabel>Benchmark comparison</CardLabel>
              <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
                <div>
                  <div className="font-display text-2xl text-ink tabular">{fmtNum(data.benchmark.actual_carbon_per_sqm, 0)}</div>
                  <div className="text-[11px] text-ink-faint">this project (kg/sqm)</div>
                </div>
                <div>
                  <div className="font-display text-2xl text-ink-soft tabular">{fmtNum(data.benchmark.baseline_carbon_per_sqm, 0)}</div>
                  <div className="text-[11px] text-ink-faint">typical (kg/sqm)</div>
                </div>
                <Badge tone={data.benchmark.comparison_label.includes("above") ? "amber" : data.benchmark.comparison_label.includes("below") ? "moss" : "neutral"}>
                  {data.benchmark.comparison_label} · {fmtPct(data.benchmark.pct_difference_from_baseline)}
                </Badge>
              </div>
              <p className="mt-3 text-[11.5px] leading-relaxed text-ink-faint">{data.benchmark.disclaimer}</p>
            </Card>

            <Card>
              <CardLabel>GRIHA Criterion 21 (internal planning estimate)</CardLabel>
              <div className="flex flex-wrap gap-x-6 gap-y-2 text-[13px]">
                <div>
                  Baseline: <span className="text-ink tabular">{fmtKg(data.griha_criterion_21.baseline_gwp_kg)}</span>
                </div>
                <div>
                  Design: <span className="text-ink tabular">{fmtKg(data.griha_criterion_21.design_gwp_kg)}</span>
                </div>
                <div>
                  Reduction: <span className="text-moss tabular">{fmtPct(data.griha_criterion_21.pct_reduction)}</span>
                </div>
              </div>
              <p className="mt-3 text-[11.5px] leading-relaxed text-ink-faint">{data.griha_criterion_21.disclaimer}</p>
            </Card>

            <Card>
              <CardLabel>Cost estimate</CardLabel>
              <Table>
                <THead>
                  <tr>
                    <Th>Material</Th>
                    <Th align="right">Quantity</Th>
                    <Th align="right">Rate used</Th>
                    <Th align="right">Cost</Th>
                  </tr>
                </THead>
                <tbody>
                  {data.cost.breakdown.map((b, i) => (
                    <tr key={i}>
                      <Td>{b.material}</Td>
                      <Td align="right">
                        {fmtNum(b.quantity, 1)} {b.quantity_unit}
                      </Td>
                      <Td align="right">
                        {fmtNum(b.rate_used, 0)}/{b.rate_unit}
                      </Td>
                      <Td align="right">{fmtInr(b.cost_inr)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              <p className="mt-3 text-[11.5px] leading-relaxed text-ink-faint">{data.cost.disclaimer}</p>
            </Card>
          </>
        )}
      </div>

      <div className="flex flex-col gap-4">
        <Card>
          <CardLabel>Tier 1 — mandatory</CardLabel>
          <FieldRow label="GFA" fv={project.mandatory.gfa_sqm} unit=" sqm" />
          <FieldRow label="Location" fv={project.mandatory.location} />
          <FieldRow label="Structural system" fv={project.mandatory.structural_system_type} />
        </Card>
        <Card>
          <CardLabel>Tier 2</CardLabel>
          <FieldRow label="Typology" fv={project.tier2.typology} />
          <FieldRow label="Floors" fv={project.tier2.num_floors} />
          <FieldRow label="Has basement" fv={project.tier2.has_basement} />
          <FieldRow label="Foundation" fv={project.tier2.foundation_type} />
          <FieldRow label="Finish level" fv={project.tier2.finish_spec_level} />
          <FieldRow label="Parking" fv={project.tier2.parking_type} />
        </Card>
        <Card>
          <CardLabel>Tier 3</CardLabel>
          <FieldRow label="Concrete grade" fv={project.tier3.concrete_grade_mix} />
          <FieldRow label="Cement type" fv={project.tier3.cement_type} />
          <FieldRow label="Steel ratio" fv={project.tier3.steel_reinforcement_ratio_kg_per_sqm} unit=" kg/sqm" />
          <FieldRow label="Facade" fv={project.tier3.facade_type} />
          <FieldRow label="Glazing" fv={project.tier3.glazing_pct} unit="%" />
          <FieldRow label="MEP complexity" fv={project.tier3.mep_complexity} />
        </Card>
      </div>
    </div>
  );
}
