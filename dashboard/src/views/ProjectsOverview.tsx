import { Link } from "react-router-dom";
import { useDriftStore } from "../data/store";
import {
  StalenessBadge,
  ModeBadge,
  ProgressBar,
  TimeAgo,
  MetricCard,
} from "../components/SharedUI";

export default function ProjectsOverview() {
  const projects = useDriftStore((s) => s.projects);
  const loading = useDriftStore((s) => s.loading);
  const error = useDriftStore((s) => s.error);

  if (loading && projects.length === 0) {
    return (
      <div className="api-gate">
        <div className="api-gate-spinner" />
        <p>Loading projects&hellip;</p>
      </div>
    );
  }

  if (error && projects.length === 0) {
    return (
      <div className="api-gate">
        <h2>Error</h2>
        <p>{error}</p>
      </div>
    );
  }

  const totalHigh = projects.reduce(
    (n, p) => n + (p.summary?.high_impact ?? 0),
    0,
  );
  const totalMedium = projects.reduce(
    (n, p) => n + (p.summary?.medium_impact ?? 0),
    0,
  );
  const totalLow = projects.reduce(
    (n, p) => n + (p.summary?.low_impact ?? 0),
    0,
  );

  return (
    <>
      <div className="view-header">
        <h2>Projects</h2>
        <div className="view-desc">
          All projects tracked by drift. Select a project to view its manifest
          and attack plan.
        </div>
      </div>

      <div className="metrics-row">
        <MetricCard label="Projects" value={projects.length} />
        <MetricCard label="High Impact" value={totalHigh} />
        <MetricCard label="Medium Impact" value={totalMedium} />
        <MetricCard label="Low Impact" value={totalLow} />
      </div>

      {projects.length === 0 ? (
        <div className="panel">
          <div className="panel-body">
            <div className="empty-state">
              No projects found. Run <code>drift audit</code> in a project
              directory to get started.
            </div>
          </div>
        </div>
      ) : (
        <div className="project-grid">
          {projects.map((p) => (
            <Link
              key={p.name}
              to={`/project/${encodeURIComponent(p.name)}`}
              className="project-card stagger-in"
            >
              <div className="project-card-header">
                <span className="project-card-name">{p.name}</span>
                <StalenessBadge staleness={p.staleness} />
              </div>

              <div className="project-card-impacts">
                {p.summary ? (
                  <>
                    <span style={{ color: "var(--high)" }}>
                      H:{p.summary.high_impact ?? 0}
                    </span>
                    <span style={{ color: "var(--medium)" }}>
                      M:{p.summary.medium_impact ?? 0}
                    </span>
                    <span style={{ color: "var(--low)" }}>
                      L:{p.summary.low_impact ?? 0}
                    </span>
                  </>
                ) : (
                  <span className="text-muted">No manifest data</span>
                )}
              </div>

              <ProgressBar progress={p.planProgress} />

              <div className="project-card-footer">
                <ModeBadge mode={p.mode} />
                <TimeAgo date={p.lastRun} />
              </div>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
