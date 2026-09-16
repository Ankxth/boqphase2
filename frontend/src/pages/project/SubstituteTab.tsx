import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, Leaf } from "lucide-react";
import { apiErrorMessage, substituteProject } from "../../lib/api";
import { fmtKg, fmtPct } from "../../lib/format";
import type { ProjectSchema } from "../../lib/types";
import { useCompany } from "../../lib/useCompany";
import { Badge } from "../../components/ui/Badge";
import { Card, CardLabel } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/EmptyState";
import { Spinner } from "../../components/ui/Spinner";

export default function SubstituteTab({ project }: { project: ProjectSchema }) {
  const { companyId } = useCompany();
  const { data, isLoading, error } = useQuery({
    queryKey: ["substitute", companyId, project.project_id],
    queryFn: () => substituteProject(project.project_id, companyId),
  });

  if (isLoading) return <Spinner label="Recomputing each real substitution…" />;
  if (error)
    return (
      <Card accent="amber">
        <p className="text-[13px] text-amber">{apiErrorMessage(error)}</p>
      </Card>
    );

  const suggestions = data?.suggestions ?? [];

  return (
    <div className="flex flex-col gap-4">
      <p className="max-w-xl text-[13px] text-ink-soft">
        Every figure below is a real re-run of the calculation engine on a cloned project — never an estimated delta.
      </p>

      {suggestions.length === 0 && (
        <EmptyState
          icon={<Leaf size={26} />}
          title="No substitution suggested right now"
          body="This project's cement type and steel ratio are already inside the recommended range, or there isn't enough set (grade, ratio) to compute one."
        />
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {suggestions.map((s, i) => (
          <Card key={i} accent={s.requires_engineering_review ? "amber" : "moss"}>
            <div className="flex items-start justify-between gap-2">
              <CardLabel>{s.substitution_id?.toString().replace(/_/g, " ") ?? `Suggestion ${i + 1}`}</CardLabel>
              {s.requires_engineering_review && (
                <Badge tone="amber">
                  <AlertTriangle size={10} /> review
                </Badge>
              )}
            </div>
            {(s.current_value || s.suggested_value) && (
              <div className="mb-3 flex items-center gap-2 text-[13px] text-ink">
                <span className="text-ink-soft">{String(s.current_value ?? "—")}</span>
                <ArrowRight size={13} className="text-ink-faint" />
                <span className="text-moss">{String(s.suggested_value ?? "—")}</span>
              </div>
            )}
            <div className="flex items-baseline gap-4">
              <div>
                <div className="font-display text-xl text-ink tabular">{fmtKg(s.carbon_kg_before)}</div>
                <div className="text-[10.5px] text-ink-faint">before</div>
              </div>
              <ArrowRight size={14} className="text-ink-faint" />
              <div>
                <div className="font-display text-xl text-moss tabular">{fmtKg(s.carbon_kg_after)}</div>
                <div className="text-[10.5px] text-ink-faint">after</div>
              </div>
            </div>
            <div className="mt-3 flex items-center gap-2 border-t border-line pt-3 text-[12.5px]">
              <span className="text-moss">
                −{fmtKg(s.savings_kg)} ({fmtPct(s.savings_pct)})
              </span>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
