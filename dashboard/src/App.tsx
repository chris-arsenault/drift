import { useEffect } from "react";
import { Routes, Route } from "react-router-dom";
import { useDriftStore } from "./data/store";
import Sidebar from "./components/Sidebar";
import ProjectsOverview from "./views/ProjectsOverview";
import ProjectDetail from "./views/ProjectDetail";
import LibraryBrowser from "./views/LibraryBrowser";

export default function App() {
  const fetchProjects = useDriftStore((s) => s.fetchProjects);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  return (
    <div className="app-layout">
      <Sidebar />
      <main className="main-content">
        <Routes>
          <Route path="/" element={<ProjectsOverview />} />
          <Route path="/project/:name" element={<ProjectDetail />} />
          <Route path="/library" element={<LibraryBrowser />} />
        </Routes>
      </main>
    </div>
  );
}
