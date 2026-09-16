import { useMemo, useState } from "react";
import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { ToastProvider } from "./components/ui/Toast";
import { CompanyContext, DEFAULT_COMPANY_ID } from "./lib/useCompany";
import BoqCalculator from "./pages/BoqCalculator";
import Factors from "./pages/Factors";
import Home from "./pages/Home";
import NewProject from "./pages/NewProject";
import NotFound from "./pages/NotFound";
import Onboarding from "./pages/Onboarding";
import ProjectDetail from "./pages/project/ProjectDetail";
import WoCalculator from "./pages/WoCalculator";

const STORAGE_KEY = "kiln.company_id";

export default function App() {
  const [companyId, setCompanyIdState] = useState<string>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) || DEFAULT_COMPANY_ID;
    } catch {
      return DEFAULT_COMPANY_ID;
    }
  });

  const setCompanyId = (id: string) => {
    setCompanyIdState(id);
    try {
      localStorage.setItem(STORAGE_KEY, id);
    } catch {
      /* ignore -- private mode / storage disabled */
    }
  };

  const value = useMemo(() => ({ companyId, setCompanyId }), [companyId]);

  return (
    <CompanyContext.Provider value={value}>
      <ToastProvider>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<Home />} />
            <Route path="projects/new" element={<NewProject />} />
            <Route path="projects/:projectId/*" element={<ProjectDetail />} />
            <Route path="tools/boq" element={<BoqCalculator />} />
            <Route path="tools/wo" element={<WoCalculator />} />
            <Route path="onboarding" element={<Onboarding />} />
            <Route path="factors" element={<Factors />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </ToastProvider>
    </CompanyContext.Provider>
  );
}
