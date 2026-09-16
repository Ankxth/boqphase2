import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { ArrowUpRight, Building2, CalendarClock, FileStack, Flame, Plus, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import { apiErrorMessage, listProjects } from "../lib/api";
import { fmtDate, titleCase } from "../lib/format";
import { useCompany } from "../lib/useCompany";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { Spinner } from "../components/ui/Spinner";
import { StatTile } from "../components/ui/StatTile";

const WS_TICKER = Array.from({ length: 14 }, (_, i) => `WS ${String(i).padStart(2, "0")}`);

export default function Home() {
  const { companyId } = useCompany();
  const { data: projects, isLoading, error } = useQuery({
    queryKey: ["projects", companyId],
    queryFn: () => listProjects(companyId),
  });

  const withBaseline = projects?.filter((p) => p.has_baseline).length ?? 0;
  const estimated = projects?.filter((p) => p.baseline_is_estimated).length ?? 0;
  const withBills = projects?.filter((p) => p.n_bills > 0).length ?? 0;

  return (
    <div className="flex flex-col gap-10">
      {/* ---- hero ---- */}
      <section className="relative overflow-hidden rounded-3xl border border-line bg-bg-card/60 px-6 py-12 md:px-12 md:py-16">
        <div
          className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full opacity-30 blur-3xl"
          style={{ background: "radial-gradient(circle, #ff6a3d, transparent 65%)" }}
        />
        <div
          className="pointer-events-none absolute -bottom-28 -left-16 h-64 w-64 rounded-full opacity-20 blur-3xl"
          style={{ background: "radial-gradient(circle, #8fae66, transparent 65%)" }}
        />
        <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-coral/30 bg-coral-soft px-3 py-1 font-mono text-[10.5px] uppercase tracking-[0.1em] text-coral">
            <Sparkles size={11} /> Concept to completion, one number at a time
          </span>
        </motion.div>
        <motion.h1
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.08, ease: [0.16, 1, 0.3, 1] }}
          className="mt-5 max-w-2xl text-[2.4rem] leading-[1.05] text-ink md:text-[3.2rem]"
        >
          Every tonne of embodied carbon, <span className="text-coral">traced back to a real number.</span>
        </motion.h1>
        <motion.p
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.16, ease: [0.16, 1, 0.3, 1] }}
          className="mt-4 max-w-lg text-[14.5px] leading-relaxed text-ink-soft"
        >
          Estimate at concept stage, refine against a real Bill of Quantities or Work Order, track what's actually billed
          against your baseline, and ask a chatbot that only ever reports a real recomputed figure &mdash; never a guess.
        </motion.p>
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.24, ease: [0.16, 1, 0.3, 1] }}
          className="mt-7 flex flex-wrap gap-3"
        >
          <Link to="/projects/new">
            <Button size="lg" icon={<Plus size={16} />}>
              New project
            </Button>
          </Link>
          <Link to="/tools/boq">
            <Button size="lg" variant="secondary" icon={<ArrowUpRight size={16} />}>
              Calculate from a BOQ
            </Button>
          </Link>
        </motion.div>

        <div className="relative mt-11 overflow-hidden border-t border-line pt-4">
          <div className="flex w-max animate-marquee gap-8 font-mono text-[11px] uppercase tracking-[0.14em] text-ink-faint">
            {[...WS_TICKER, ...WS_TICKER].map((w, i) => (
              <span key={i} className="flex items-center gap-2">
                <Flame size={10} className="text-coral/50" /> {w}
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* ---- stats ---- */}
      <section className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatTile label="Projects tracked" value={projects?.length ?? "—"} icon={<Building2 size={16} />} tone="coral" delay={0} />
        <StatTile label="With a baseline" value={withBaseline} icon={<FileStack size={16} />} tone="moss" delay={0.05} />
        <StatTile
          label="Phase 1-estimated"
          value={estimated}
          sub="running without a real BOQ/WO yet"
          icon={<Sparkles size={16} />}
          tone="amber"
          delay={0.1}
        />
        <StatTile label="Being billed" value={withBills} icon={<CalendarClock size={16} />} tone="coral" delay={0.15} />
      </section>

      {/* ---- project list ---- */}
      <section>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-xl text-ink">Your projects</h2>
          <Link to="/projects/new">
            <Button variant="ghost" size="sm" icon={<Plus size={14} />}>
              New
            </Button>
          </Link>
        </div>

        {isLoading && <Spinner label="Loading projects…" />}

        {error && (
          <Card accent="amber">
            <p className="text-[13px] text-amber">{apiErrorMessage(error)}</p>
          </Card>
        )}

        {!isLoading && !error && (projects?.length ?? 0) === 0 && (
          <EmptyState
            icon={<Building2 size={30} />}
            title="No projects yet for this company"
            body={`Nothing found for company_id "${companyId}". Start a new project, or check the company id in the top bar.`}
            action={
              <Link to="/projects/new">
                <Button icon={<Plus size={15} />}>Start your first project</Button>
              </Link>
            }
          />
        )}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects?.map((p, i) => (
            <motion.div key={p.project_id} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, delay: i * 0.04 }}>
              <Link to={`/projects/${p.project_id}`}>
                <Card className="group h-full cursor-pointer transition-colors hover:border-coral/40">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate font-display text-[16px] text-ink">{p.project_name || "Untitled project"}</div>
                      <div className="mt-0.5 truncate font-mono text-[10.5px] text-ink-faint">{p.project_id}</div>
                    </div>
                    <ArrowUpRight size={16} className="mt-1 shrink-0 text-ink-faint transition-colors group-hover:text-coral" />
                  </div>

                  <div className="mt-4 flex flex-wrap gap-1.5">
                    {p.has_phase1_record ? <Badge tone="moss">Phase 1 record</Badge> : <Badge tone="neutral">No Phase 1 yet</Badge>}
                    {p.has_baseline ? (
                      <Badge tone={p.baseline_is_estimated ? "amber" : "coral"}>
                        {p.baseline_is_estimated ? "Estimated baseline" : titleCase(p.baseline_source_type ?? undefined)}
                      </Badge>
                    ) : (
                      <Badge tone="neutral">No baseline</Badge>
                    )}
                  </div>

                  <div className="mt-4 flex items-center justify-between border-t border-line pt-3 text-[11.5px] text-ink-faint">
                    <span>{p.n_bills} bill{p.n_bills === 1 ? "" : "s"} recorded</span>
                    <span>{p.latest_billed_date ? fmtDate(p.latest_billed_date) : "—"}</span>
                  </div>
                </Card>
              </Link>
            </motion.div>
          ))}
        </div>
      </section>
    </div>
  );
}
