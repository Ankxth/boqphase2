import { useMutation } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { useState } from "react";
import { apiErrorMessage, editProject } from "../../lib/api";
import type { FormSubmission, ProjectSchema } from "../../lib/types";
import { useCompany } from "../../lib/useCompany";
import { Button } from "../../components/ui/Button";
import { Card, CardLabel } from "../../components/ui/Card";
import { Field, Select, TextInput } from "../../components/ui/Field";
import { useToast } from "../../components/ui/Toast";

function fromProject(p: ProjectSchema): FormSubmission {
  return {
    project_name: p.project_name,
    gfa_sqm: p.mandatory.gfa_sqm.value,
    location: p.mandatory.location.value,
    structural_system_type: p.mandatory.structural_system_type.value,
    typology: p.tier2.typology.value,
    num_floors: p.tier2.num_floors.value,
    has_basement: p.tier2.has_basement.value,
    basement_count: p.tier2.basement_count.value,
    foundation_type: p.tier2.foundation_type.value,
    finish_spec_level: p.tier2.finish_spec_level.value,
    parking_type: p.tier2.parking_type.value,
    parking_area_sqm: p.tier2.parking_area_sqm.value,
    concrete_grade_mix: p.tier3.concrete_grade_mix.value,
    cement_type: p.tier3.cement_type.value,
    steel_reinforcement_ratio_kg_per_sqm: p.tier3.steel_reinforcement_ratio_kg_per_sqm.value,
    facade_type: p.tier3.facade_type.value,
    glazing_pct: p.tier3.glazing_pct.value,
    mep_complexity: p.tier3.mep_complexity.value,
    green_cert_target: p.tier3.green_cert_target.value,
    site_condition: p.tier3.site_condition.value,
  };
}

export default function EditTab({ project, onSaved }: { project: ProjectSchema; onSaved: () => void }) {
  const { companyId } = useCompany();
  const toast = useToast();
  const [form, setForm] = useState<FormSubmission>(() => fromProject(project));
  const set = <K extends keyof FormSubmission>(key: K, value: FormSubmission[K]) => setForm((f) => ({ ...f, [key]: value }));

  const mutation = useMutation({
    mutationFn: () => editProject(project.project_id, companyId, form),
    onSuccess: () => {
      toast.success("Saved — your edits now override any matched or estimated value.");
      onSaved();
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        mutation.mutate();
      }}
      className="flex flex-col gap-5"
    >
      <p className="max-w-xl text-[13px] text-ink-soft">
        Anything you change here overwrites the existing value and is tagged <span className="text-moss">user-entered</span>{" "}
        — it always outranks a matched or estimated one. Fields you leave alone are untouched.
      </p>

      <Card>
        <CardLabel>Project</CardLabel>
        <Field label="Project name">
          <TextInput value={form.project_name ?? ""} onChange={(e) => set("project_name", e.target.value || null)} />
        </Field>
      </Card>

      <Card accent="coral">
        <CardLabel>Tier 1</CardLabel>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Gross floor area (sqm)">
            <TextInput type="number" value={form.gfa_sqm ?? ""} onChange={(e) => set("gfa_sqm", e.target.value === "" ? null : Number(e.target.value))} />
          </Field>
          <Field label="Location">
            <TextInput value={form.location ?? ""} onChange={(e) => set("location", e.target.value)} />
          </Field>
          <Field label="Structural system">
            <Select value={form.structural_system_type ?? ""} onChange={(e) => set("structural_system_type", e.target.value as FormSubmission["structural_system_type"])}>
              <option value="">—</option>
              <option value="rcc_frame">RCC frame</option>
              <option value="load_bearing_masonry">Load-bearing masonry</option>
              <option value="steel_frame">Steel frame</option>
              <option value="composite">Composite</option>
            </Select>
          </Field>
        </div>
      </Card>

      <Card>
        <CardLabel>Tier 2</CardLabel>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Typology">
            <Select value={form.typology ?? ""} onChange={(e) => set("typology", (e.target.value || null) as FormSubmission["typology"])}>
              <option value="">—</option>
              <option value="residential">Residential</option>
              <option value="commercial">Commercial</option>
              <option value="institutional">Institutional</option>
              <option value="mixed_use">Mixed use</option>
            </Select>
          </Field>
          <Field label="Number of floors">
            <TextInput type="number" value={form.num_floors ?? ""} onChange={(e) => set("num_floors", e.target.value === "" ? null : Number(e.target.value))} />
          </Field>
          <Field label="Has basement?">
            <Select value={form.has_basement == null ? "" : String(form.has_basement)} onChange={(e) => set("has_basement", e.target.value === "" ? null : e.target.value === "true")}>
              <option value="">—</option>
              <option value="true">Yes</option>
              <option value="false">No</option>
            </Select>
          </Field>
          <Field label="Basement count">
            <TextInput type="number" value={form.basement_count ?? ""} onChange={(e) => set("basement_count", e.target.value === "" ? null : Number(e.target.value))} />
          </Field>
          <Field label="Foundation type">
            <Select value={form.foundation_type ?? ""} onChange={(e) => set("foundation_type", (e.target.value || null) as FormSubmission["foundation_type"])}>
              <option value="">—</option>
              <option value="isolated_footing">Isolated footing</option>
              <option value="raft">Raft</option>
              <option value="pile">Pile</option>
              <option value="combined_footing">Combined footing</option>
            </Select>
          </Field>
          <Field label="Finish spec level">
            <Select value={form.finish_spec_level ?? ""} onChange={(e) => set("finish_spec_level", (e.target.value || null) as FormSubmission["finish_spec_level"])}>
              <option value="">—</option>
              <option value="economical">Economical</option>
              <option value="standard">Standard</option>
              <option value="premium">Premium</option>
            </Select>
          </Field>
          <Field label="Parking type">
            <TextInput value={form.parking_type ?? ""} onChange={(e) => set("parking_type", e.target.value || null)} />
          </Field>
          <Field label="Parking area (sqm)">
            <TextInput type="number" value={form.parking_area_sqm ?? ""} onChange={(e) => set("parking_area_sqm", e.target.value === "" ? null : Number(e.target.value))} />
          </Field>
        </div>
      </Card>

      <Card>
        <CardLabel>Tier 3</CardLabel>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Concrete grade mix">
            <TextInput value={form.concrete_grade_mix ?? ""} onChange={(e) => set("concrete_grade_mix", e.target.value || null)} />
          </Field>
          <Field label="Cement type">
            <Select value={form.cement_type ?? ""} onChange={(e) => set("cement_type", (e.target.value || null) as FormSubmission["cement_type"])}>
              <option value="">—</option>
              <option value="OPC">OPC</option>
              <option value="PSC">PSC</option>
              <option value="PPC">PPC</option>
            </Select>
          </Field>
          <Field label="Steel reinforcement ratio (kg/sqm)">
            <TextInput
              type="number"
              value={form.steel_reinforcement_ratio_kg_per_sqm ?? ""}
              onChange={(e) => set("steel_reinforcement_ratio_kg_per_sqm", e.target.value === "" ? null : Number(e.target.value))}
            />
          </Field>
          <Field label="Facade type">
            <TextInput value={form.facade_type ?? ""} onChange={(e) => set("facade_type", e.target.value || null)} />
          </Field>
          <Field label="Glazing (%)">
            <TextInput type="number" min={0} max={100} value={form.glazing_pct ?? ""} onChange={(e) => set("glazing_pct", e.target.value === "" ? null : Number(e.target.value))} />
          </Field>
          <Field label="MEP complexity">
            <Select value={form.mep_complexity ?? ""} onChange={(e) => set("mep_complexity", (e.target.value || null) as FormSubmission["mep_complexity"])}>
              <option value="">—</option>
              <option value="basic">Basic</option>
              <option value="standard">Standard</option>
              <option value="complex">Complex</option>
            </Select>
          </Field>
          <Field label="Green cert target">
            <TextInput value={form.green_cert_target ?? ""} onChange={(e) => set("green_cert_target", e.target.value || null)} />
          </Field>
          <Field label="Site condition">
            <Select value={form.site_condition ?? ""} onChange={(e) => set("site_condition", (e.target.value || null) as FormSubmission["site_condition"])}>
              <option value="">—</option>
              <option value="normal_soil">Normal soil</option>
              <option value="rocky">Rocky</option>
              <option value="waterlogged">Waterlogged</option>
              <option value="reclaimed_land">Reclaimed land</option>
            </Select>
          </Field>
        </div>
      </Card>

      <div className="flex justify-end">
        <Button type="submit" size="lg" loading={mutation.isPending} icon={<Save size={15} />}>
          Save changes
        </Button>
      </div>
    </form>
  );
}
