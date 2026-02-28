import { NavLink } from "react-router-dom";
import { FolderKanban, Library, CircleDot } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useDriftStore } from "../data/store";

// ── Nav definition ──────────────────────────────────────────────────────

type NavSection = { section: string };
type NavLink_ = { path: string; label: string; icon: LucideIcon };
type NavEntry = NavSection | NavLink_;

function isSection(item: NavEntry): item is NavSection {
  return "section" in item;
}

const NAV_ITEMS: NavEntry[] = [
  { section: "Overview" },
  { path: "/", label: "Projects", icon: FolderKanban },

  { section: "Shared" },
  { path: "/library", label: "Library", icon: Library },
];

// ── Component ───────────────────────────────────────────────────────────

export default function Sidebar() {
  const projects = useDriftStore((s) => s.projects);

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <h1>drift</h1>
        <div className="subtitle">semantic drift dashboard</div>
      </div>

      <nav className="sidebar-nav">
        {NAV_ITEMS.map((item, i) => {
          if (isSection(item)) {
            return (
              <div key={i} className="nav-section-label">
                {item.section}
              </div>
            );
          }
          const Icon = item.icon;
          return (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === "/"}
              className={({ isActive }) =>
                `nav-item ${isActive ? "active" : ""}`
              }
            >
              <Icon />
              <span>{item.label}</span>
            </NavLink>
          );
        })}

        {/* Dynamic project shortcuts */}
        {projects.length > 0 && (
          <>
            <div className="nav-section-label">Projects</div>
            {projects.map((p) => (
              <NavLink
                key={p.name}
                to={`/project/${encodeURIComponent(p.name)}`}
                className={({ isActive }) =>
                  `nav-item ${isActive ? "active" : ""}`
                }
              >
                <CircleDot />
                <span>{p.name}</span>
                {p.summary?.high_impact ? (
                  <span className="nav-badge">{p.summary.high_impact}</span>
                ) : null}
              </NavLink>
            ))}
          </>
        )}
      </nav>
    </aside>
  );
}
