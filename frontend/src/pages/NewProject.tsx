import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, Layers, Sparkles } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiErrorMessage, submitForm } from "../lib/api";
import type { FormSubmission } from "../lib/types";
import { useCompany } from "../lib/useCompany";
import { Accordion } from "../components/ui/Accordion";
import { Button } from "../components/ui/Button";
import { Card, CardLabel } from "../components/ui/Card";
import { Field, Select, TextInput } from "../components/ui/Field";
import { useToast } from "../components/ui/Toast";

export default function NewProject() {
  const { companyId } = useCompany();
  const navigate = useNavigate();
  const toast = useToast();

  const [form, setForm] = useState<FormSubmission>({});
  const set = <K extends keyof FormSubmission>(key: K, value: FormSubmission[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const mutation = useMutation({
    mutationFn: () => submitForm({ ...form, company_id: companyId }),
    onSuccess: (project) => {
      toast.success("Project created — Phase 1 filled in what it could.");
      navigate(`/projects/${project.project_id}`);
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  return (
    <div className="mx-auto max-w-2xl">
      <button onClick={() => navigate(-1)} className="mb-5 inline-flex items-center gap-1.5 text-[12.5px] text-ink-faint hover:text-ink">
        <ArrowLeft size={14} /> Back
      </button>

      <h1 className="text-2xl text-ink">Start a new project</h1>
      <p className="mt-2 max-w-lg text-[13.5px] text-ink-soft">
        Only the three mandatory fields below are required — Phase 1 auto-fills whatever's left, first by matching a
        reference BOQ, then with an LLM estimate, and tags each field with exactly where the value came from. Give it
        more (Tiers 2 &amp; 3) and it needs to guess less.
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate();
        }}
        className="mt-7 flex flex-col gap-5"
      >
        <Card>
          <CardLabel>Project</CardLabel>
          <Field label="Project name" hint="A human-readable label, e.g. “Ecopolitan Phase 2.” Optional.">
            <TextInput
              value={form.project_name ?? ""}
              onChange={(e) => set("project_name", e.target.value || null)}
              placeholder="Untitled project"
            />
          </Field>
        </Card>

        <Card accent="coral">
          <CardLabel>Mandatory — Tier 1</CardLabel>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Gross floor area (sqm)">
              <TextInput
                type="number"
                min={0}
                required
                value={form.gfa_sqm ?? ""}
                onChange={(e) => set("gfa_sqm", e.target.value === "" ? null : Number(e.target.value))}
                placeholder="40000"
              />
            </Field>
            <Field label="Location">
              <TextInput
                required
                value={form.location ?? ""}
                onChange={(e) => set("location", e.target.value)}
                placeholder="Bengaluru"
              />
            </Field>
            <Field label="Structural system">
              <Select
                required
                value={form.structural_system_type ?? ""}
                onChange={(e) => set("structural_system_type", e.target.value as FormSubmission["structural_system_type"])}
              >
                <option value="" disabled>
                  Select…
                </option>
                <option value="rcc_frame">RCC frame</option>
                <option value="load_bearing_masonry">Load-bearing masonry</option>
                <option value="steel_frame">Steel frame</option>
                <option value="composite">Composite</option>
              </Select>
            </Field>
          </div>
        </Card>

        <Accordion
          title={
            <span className="flex items-center gap-2">
              <Layers size={14} className="text-ink-faint" /> Tier 2 — sharpen the shape
            </span>
          }
          subtitle="Typology, floors, foundation, finish level, parking"
        >
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Typology">
              <Select value={form.typology ?? ""} onChange={(e) => set("typology", (e.target.value || null) as FormSubmission["typology"])}>
                <option value="">Let it estimate…</option>
                <option value="residential">Residential</option>
                <option value="commercial">Commercial</option>
                <option value="institutional">Institutional</option>
                <option value="mixed_use">Mixed use</option>
              </Select>
            </Field>
            <Field label="Number of floors">
              <TextInput
                type="number"
                min={0}
                value={form.num_floors ?? ""}
                onChange={(e) => set("num_floors", e.target.value === "" ? null : Number(e.target.value))}
              />
            </Field>
            <Field label="Has basement?">
              <Select
                value={form.has_basement == null ? "" : String(form.has_basement)}
                onChange={(e) => set("has_basement", e.target.value === "" ? null : e.target.value === "true")}
              >
                <option value="">Let it estimate…</option>
                <option value="true">Yes</option>
                <option value="false">No</option>
              </Select>
            </Field>
            <Field label="Basement count" hint="If it has one">
              <TextInput
                type="number"
                min={0}
                disabled={form.has_basement !== true}
                value={form.basement_count ?? ""}
                onChange={(e) => set("basement_count", e.target.value === "" ? null : Number(e.target.value))}
              />
            </Field>
            <Field label="Foundation type">
              <Select value={form.foundation_type ?? ""} onChange={(e) => set("foundation_type", (e.target.value || null) as FormSubmission["foundation_type"])}>
                <option value="">Let it estimate…</option>
                <option value="isolated_footing">Isolated footing</option>
                <option value="raft">Raft</option>
                <option value="pile">Pile</option>
                <option value="combined_footing">Combined footing</option>
              </Select>
            </Field>
            <Field label="Finish spec level">
              <Select value={form.finish_spec_level ?? ""} onChange={(e) => set("finish_spec_level", (e.target.value || null) as FormSubmission["finish_spec_level"])}>
                <option value="">Let it estimate…</option>
                <option value="economical">Economical</option>
                <option value="standard">Standard</option>
                <option value="premium">Premium</option>
              </Select>
            </Field>
            <Field label="Parking type">
              <TextInput value={form.parking_type ?? ""} onChange={(e) => set("parking_type", e.target.value || null)} placeholder="basement / surface / multi-level" />
            </Field>
            <Field label="Parking area (sqm)">
              <TextInput
                type="number"
                min={0}
                value={form.parking_area_sqm ?? ""}
                onChange={(e) => set("parking_area_sqm", e.target.value === "" ? null : Number(e.target.value))}
              />
            </Field>
          </div>
        </Accordion>

        <Accordion
          title={
            <span className="flex items-center gap-2">
              <Sparkles size={14} className="text-ink-faint" /> Tier 3 — the numbers the engine actually runs on
            </span>
          }
          subtitle="Concrete grade, cement type, steel ratio, facade, MEP, site"
        >
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Concrete grade mix" hint="e.g. M30">
              <TextInput value={form.concrete_grade_mix ?? ""} onChange={(e) => set("concrete_grade_mix", e.target.value || null)} placeholder="M30" />
            </Field>
            <Field label="Cement type">
              <Select value={form.cement_type ?? ""} onChange={(e) => set("cement_type", (e.target.value || null) as FormSubmission["cement_type"])}>
                <option value="">Let it estimate…</option>
                <option value="OPC">OPC</option>
                <option value="PSC">PSC</option>
                <option value="PPC">PPC</option>
              </Select>
            </Field>
            <Field label="Steel reinforcement ratio (kg/sqm)">
              <TextInput
                type="number"
                min={0}
                value={form.steel_reinforcement_ratio_kg_per_sqm ?? ""}
                onChange={(e) => set("steel_reinforcement_ratio_kg_per_sqm", e.target.value === "" ? null : Number(e.target.value))}
              />
            </Field>
            <Field label="Facade type">
              <TextInput value={form.facade_type ?? ""} onChange={(e) => set("facade_type", e.target.value || null)} placeholder="curtain wall / punched window" />
            </Field>
            <Field label="Glazing (% of facade)">
              <TextInput
                type="number"
                min={0}
                max={100}
                value={form.glazing_pct ?? ""}
                onChange={(e) => set("glazing_pct", e.target.value === "" ? null : Number(e.target.value))}
              />
            </Field>
            <Field label="MEP complexity">
              <Select value={form.mep_complexity ?? ""} onChange={(e) => set("mep_complexity", (e.target.value || null) as FormSubmission["mep_complexity"])}>
                <option value="">Let it estimate…</option>
                <option value="basic">Basic</option>
                <option value="standard">Standard</option>
                <option value="complex">Complex</option>
              </Select>
            </Field>
            <Field label="Green cert target">
              <TextInput value={form.green_cert_target ?? ""} onChange={(e) => set("green_cert_target", e.target.value || null)} placeholder="GRIHA 3-star / none" />
            </Field>
            <Field label="Site condition">
              <Select value={form.site_condition ?? ""} onChange={(e) => set("site_condition", (e.target.value || null) as FormSubmission["site_condition"])}>
                <option value="">Let it estimate…</option>
                <option value="normal_soil">Normal soil</option>
                <option value="rocky">Rocky</option>
                <option value="waterlogged">Waterlogged</option>
                <option value="reclaimed_land">Reclaimed land</option>
              </Select>
            </Field>
          </div>
        </Accordion>

        <div className="flex justify-end">
          <Button type="submit" size="lg" loading={mutation.isPending}>
            Create project
          </Button>
        </div>
      </form>
    </div>
  );
}
