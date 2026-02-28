import { useEffect } from "react";
import { Routes, Route } from "react-router-dom";
import { useDriftStore } from "./data/store";
import Sidebar from "./components/Sidebar";
import ProjectsOverview from "./views/ProjectsOverview";
import ProjectDetail from "./views/ProjectDetail";
import LibraryBrowser from "./views/LibraryBrowser";

export default function App() {
  const loading = useDriftStore((s) => s.loading);
  const error = useDriftStore((s) => s.error);
  const fetchProjects = useDriftStore((s) => s.fetchProjects);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  return (
    <div className="app-layout">
      <Sidebar />
      <main className="main-content">
        {loading && (
          <div className="api-gate">
            <div className="api-gate-spinner" />
            <p>Loading&hellip;</p>
          </div>
        )}
        {error && !loading && (
          <div className="api-gate">
            <h2>Error</h2>
            <p>{error}</p>
            <button className="btn btn-accent" onClick={fetchProjects}>
              Retry
            </button>
          </div>
        )}
        {!loading && !error && (
          <Routes>
            <Route path="/" element={<ProjectsOverview />} />
            <Route path="/project/:name" element={<ProjectDetail />} />
            <Route path="/library" element={<LibraryBrowser />} />
          </Routes>
        )}
      </main>
    </div>
  );
}
