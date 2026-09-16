import { BrowserRouter, Routes, Route, Navigate, useNavigate } from "react-router-dom";
import { useState } from "react";
import Shell from "./components/Shell";
import TieredForm from "./screens/TieredForm";
import ReviewForm from "./screens/ReviewForm";
import Dashboard from "./screens/Dashboard";
import BoqCarbonUpload from "./screens/BoqCarbonUpload";
import BoqCarbonResults from "./screens/BoqCarbonResults";

function Flow() {
  const [projectId, setProjectId] = useState(null);
  const [boqResult, setBoqResult] = useState(null);
  const [boqParams, setBoqParams] = useState(null); // { file, sheetName, floorAreaSqm, floorAreaBasis } from the upload step -- the substitution panel needs these to re-call the stateless /boq-carbon/substitute endpoint
  const navigate = useNavigate();

  function reset() {
    setProjectId(null);
    navigate("/");
  }

  function resetBoqCarbon() {
    setBoqResult(null);
    setBoqParams(null);
    navigate("/boq-carbon");
  }

  return (
    <Shell projectId={projectId}>
      <Routes>
        {/* Phase 1: tiered conceptual estimator */}
        <Route
          path="/"
          element={
            <TieredForm
              onSubmitted={(project) => {
                setProjectId(project.project_id);
                navigate("/review");
              }}
            />
          }
        />
        <Route
          path="/review"
          element={
            projectId ? (
              <ReviewForm
                projectId={projectId}
                onBack={reset}
                onProceed={() => navigate("/result")}
              />
            ) : (
              <Navigate to="/" replace />
            )
          }
        />
        <Route
          path="/result"
          element={
            projectId ? (
              <Dashboard projectId={projectId} onStartOver={reset} />
            ) : (
              <Navigate to="/" replace />
            )
          }
        />

        {/* Phase 2: raw-BOQ-upload pipeline -- standalone from the tiered flow
            above, no project_id / persistence, result held in memory only. */}
        <Route
          path="/boq-carbon"
          element={
            <BoqCarbonUpload
              onComputed={(result, params) => {
                setBoqResult(result);
                setBoqParams(params);
                navigate("/boq-carbon/result");
              }}
            />
          }
        />
        <Route
          path="/boq-carbon/result"
          element={
            boqResult ? (
              <BoqCarbonResults result={boqResult} boqParams={boqParams} onStartOver={resetBoqCarbon} />
            ) : (
              <Navigate to="/boq-carbon" replace />
            )
          }
        />
      </Routes>
    </Shell>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Flow />
    </BrowserRouter>
  );
}
