import { NavLink, useLocation } from "react-router-dom";
import { useEffect, useState } from "react";
import { pingBackend } from "../api";

const conceptualSteps = [
  { path: "/", label: "Project Details", n: "01", enabled: true },
  { path: "/review", label: "Review & Refine", n: "02", enabled: true },
  { path: "/result", label: "Results", n: "03", enabled: true },
];

const boqCarbonSteps = [
  { path: "/boq-carbon", label: "Upload BOQ", n: "01", enabled: true },
  { path: "/boq-carbon/result", label: "Results", n: "02", enabled: true },
];

// Two independent flows share this app: the tiered conceptual estimator
// (Phase 1, routes "/", "/review", "/result") and the raw-BOQ-upload
// pipeline (Phase 2, routes "/boq-carbon", "/boq-carbon/result"). The
// mode switcher below is the only thing that lets a user move between
// them -- everything else in this Shell (title block, footer, blueprint
// styling) stays identical across both so the two phases read as one
// product, not two bolted-together tools.
export default function Shell({ children, projectId }) {
  const [backendUp, setBackendUp] = useState(null); // null = checking, true/false after first ping
  const location = useLocation();
  const inBoqCarbonMode = location.pathname.startsWith("/boq-carbon");
  const steps = inBoqCarbonMode ? boqCarbonSteps : conceptualSteps;

  useEffect(() => {
    let cancelled = false;
    async function check() {
      const ok = await pingBackend();
      if (!cancelled) setBackendUp(ok);
    }
    check();
    const interval = setInterval(check, 8000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  return (
    <div className="min-h-screen blueprint-grid">
      {/* Title block */}
      <header className="border-b border-ink bg-ink text-paper">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div>
            <p className="spec-label !text-cyan-dim">Conceptual Stage · Embodied Carbon</p>
            <h1 className="font-display text-3xl tracking-wide leading-none mt-1">
              Carbon Calculator
            </h1>
          </div>
          <div className="flex items-center gap-4">
            {!inBoqCarbonMode && (
              <span className="spec-label !text-cyan-dim">
                Project: {projectId ? projectId.slice(0, 8) : "—"}
              </span>
            )}
            <span
              className="spec-label !text-cyan-dim flex items-center gap-2"
              title={
                backendUp === null
                  ? "Checking connection to the FastAPI backend…"
                  : backendUp
                  ? "Connected to backend at localhost:8000"
                  : "Cannot reach backend at localhost:8000 — is uvicorn running?"
              }
            >
              <span
                className="status-dot"
                style={{
                  backgroundColor:
                    backendUp === null ? "#8a94a0" : backendUp ? "#2E7D5B" : "var(--color-safety)",
                }}
              />
              backend {backendUp === null ? "checking" : backendUp ? "connected" : "offline"}
            </span>
          </div>
        </div>
      </header>

      {/* Mode switcher -- which of the two independent flows is active */}
      <div className="border-b border-ink bg-ink/95">
        <div className="max-w-6xl mx-auto px-6 flex">
          <NavLink
            to="/"
            className={() =>
              `px-5 py-2 spec-label !text-paper border-r border-paper/20 ${
                !inBoqCarbonMode ? "bg-cyan" : "hover:bg-paper/10"
              }`
            }
          >
            Conceptual Estimator (Phase 1)
          </NavLink>
          <NavLink
            to="/boq-carbon"
            className={() =>
              `px-5 py-2 spec-label !text-paper ${inBoqCarbonMode ? "bg-cyan" : "hover:bg-paper/10"}`
            }
          >
            Upload BOQ (Phase 2)
          </NavLink>
        </div>
      </div>

      {/* Process stepper */}
      <nav className="border-b border-ink bg-paper-dim">
        <div className="max-w-6xl mx-auto px-6 flex">
          {steps.map((s) => (
            <NavLink
              key={s.label}
              to={s.path}
              end={s.path === "/" || s.path === "/boq-carbon"}
              className={({ isActive }) =>
                `flex items-center gap-2 px-5 py-3 border-r border-ink/20 font-display text-lg tracking-wide transition-colors ${
                  isActive ? "bg-cyan text-paper" : "text-ink/70 hover:bg-cyan-dim/40"
                }`
              }
            >
              <span className="data-num text-xs opacity-70">{s.n}</span>
              {s.label}
            </NavLink>
          ))}
        </div>
      </nav>

      <main className="max-w-6xl mx-auto px-6 py-8">{children}</main>

      <footer className="max-w-6xl mx-auto px-6 py-6 mt-8 border-t border-ink/20">
        <p className="spec-label">
          LLM-estimated fields (orange) need review before you trust the result. Cost figures are
          rough order-of-magnitude, not quote-ready. GRIHA points are an internal planning
          estimate, not the official GRIHA-panel result. Substitutions requiring engineering
          review must be verified by a structural engineer before implementation. Phase 2 (BOQ
          upload) uses placeholder factors for every category except concrete and reinforcement
          steel -- see the results screen for exactly which.
        </p>
      </footer>
    </div>
  );
}
