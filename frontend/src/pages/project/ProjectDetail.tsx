import { useQuery } from "@tanstack/react-query";
import axios from "axios";
import { motion } from "framer-motion";
import { AlertTriangle, ArrowLeft, BarChart3, GitCompareArrows, MessagesSquare, PencilLine, SlidersHorizontal, UploadCloud } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiErrorMessage, getProject } from "../../lib/api";
import { useCompany } from "../../lib/useCompany";
import { Badge } from "../../components/ui/Badge";
import { Card } from "../../components/ui/Card";
import { Spinner } from "../../components/ui/Spinner";
import { Tabs, type TabItem } from "../../components/ui/Tabs";
import ChatTab from "./ChatTab";
import EditTab from "./EditTab";
import OverviewTab from "./OverviewTab";
import Phase3Tab from "./Phase3Tab";
import RefineTab from "./RefineTab";
import SubstituteTab from "./SubstituteTab";

const FULL_TABS: TabItem[] = [
  { id: "overview", label: "Overview", icon: <BarChart3 size={13} /> },
  { id: "edit", label: "Edit", icon: <PencilLine size={13} /> },
  { id: "substitute", label: "What-if", icon: <SlidersHorizontal size={13} /> },
  { id: "refine", label: "Refine", icon: <UploadCloud size={13} /> },
  { id: "phase3", label: "Tracking", icon: <GitCompareArrows size={13} /> },
  { id: "chat", label: "Chat", icon: <MessagesSquare size={13} /> },
];

export default function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>();
  const { companyId } = useCompany();
  const [tab, setTab] = useState("overview");

  const { data: project, isLoading, error, refetch } = useQuery({
    queryKey: ["project", companyId, projectId],
    queryFn: () => getProject(projectId!, companyId),
    enabled: !!projectId,
    retry: false,
  });

  if (isLoading) return <Spinner label="Loading project…" />;

  // A project can exist in Phase 3 (a baseline/bills) without ever having
  // gone through Phase 1's tiered form -- GET /form/{id} 404s in exactly
  // that case. That's not a broken page, it's a narrower one: everything
  // that needs a Phase 1 record (overview/edit/what-if/refine/chat) is
  // genuinely unavailable, but tracking (baseline/bills/dashboard) isn't.
  const isMissingPhase1 = axios.isAxiosError(error) && error.response?.status === 404;

  if (error && !isMissingPhase1) {
    return (
      <Card accent="amber">
        <div className="flex items-start gap-3">
          <AlertTriangle size={18} className="mt-0.5 shrink-0 text-amber" />
          <div>
            <div className="font-medium text-ink">Couldn't load this project</div>
            <p className="mt-1 text-[13px] text-ink-soft">{apiErrorMessage(error)}</p>
            <Link to="/" className="mt-3 inline-flex items-center gap-1.5 text-[12.5px] text-coral hover:underline">
              <ArrowLeft size={13} /> Back to projects
            </Link>
          </div>
        </div>
      </Card>
    );
  }

  if (isMissingPhase1 && projectId) {
    return (
      <div className="flex flex-col gap-6">
        <ProjectHeader name="Untitled project" projectId={projectId} companyId={companyId} extraBadge={<Badge tone="amber">No Phase 1 record</Badge>} />
        <Card accent="amber">
          <p className="text-[13px] leading-relaxed text-ink-soft">
            This project was never submitted through Phase 1's tiered form (only a BOQ/Work Order baseline exists for
            it), so the overview, edit, what-if and chat tools — which all recompute against that record — aren't
            available here. Tracking (baseline, bills, the running-carbon dashboard) works the same either way.
          </p>
        </Card>
        <Phase3Tab projectId={projectId} />
      </div>
    );
  }

  if (!project) return null;

  return (
    <div className="flex flex-col gap-6">
      <ProjectHeader name={project.project_name || "Untitled project"} projectId={project.project_id} companyId={project.company_id} />

      <Tabs items={FULL_TABS} active={tab} onChange={setTab} />

      <motion.div key={tab} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        {tab === "overview" && <OverviewTab project={project} />}
        {tab === "edit" && <EditTab project={project} onSaved={refetch} />}
        {tab === "substitute" && <SubstituteTab project={project} />}
        {tab === "refine" && <RefineTab project={project} />}
        {tab === "phase3" && <Phase3Tab projectId={project.project_id} />}
        {tab === "chat" && <ChatTab projectId={project.project_id} />}
      </motion.div>
    </div>
  );
}

function ProjectHeader({ name, projectId, companyId, extraBadge }: { name: string; projectId: string; companyId: string; extraBadge?: React.ReactNode }) {
  return (
    <div>
      <Link to="/" className="mb-3 inline-flex items-center gap-1.5 text-[12.5px] text-ink-faint hover:text-ink">
        <ArrowLeft size={13} /> All projects
      </Link>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl text-ink">{name}</h1>
          <div className="mt-1 flex items-center gap-2 font-mono text-[11px] text-ink-faint">
            {projectId}
            <Badge tone="neutral">{companyId}</Badge>
            {extraBadge}
          </div>
        </div>
      </div>
    </div>
  );
}
