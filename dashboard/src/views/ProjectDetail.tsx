import { useEffect } from "react";
import { useParams } from "react-router-dom";
import { useDriftStore } from "../data/store";
import { StalenessBadge, ModeBadge, MetricCard } from "../components/SharedUI";

export default function ProjectDetail() {
  const { name } = useParams<{ name: string }>();
  const fetchProject = useDriftStore((s) => s.fetchProject);
  const project = useDriftStore((s) => s.selectedProject);
  const loading = useDriftStore((s) => s.loading);
  const error = useDriftStore((s) => s.error);

  useEffect(() => {
    if (name) fetchProject(name);
  }, [name, fetchProject]);

  if (loading) {
    return (
      <div className="api-gate">
        <div className="api-gate-spinner" />
        <p>Loading project&hellip;</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="api-gate">
        <h2>Error</h2>
        <p>{error}</p>
      </div>
    );
  }

  if (!project) {
    return (
      <div className="api-gate">
        <p>Project not found.</p>
      </div>
    );
  }

  const summary = project.manifest?.summary;

  return (
    <>
      <div className="view-header">
        <h2>{project.name}</h2>
        <div className="view-desc" style={{ display: "flex", gap: "var(--sp-2)", alignItems: "center" }}>
          <StalenessBadge staleness={project.staleness} />
          <ModeBadge mode={project.config?.mode ?? null} />
          <span>{project.path}</span>
        </div>
      </div>

      {summary ? (
        <div className="metrics-row">
          <MetricCard
            label="Drift Areas"
            value={summary.total_drift_areas ?? 0}
          />
          <MetricCard
            label="Files Affected"
            value={summary.total_files_affected ?? 0}
          />
          <MetricCard label="High" value={summary.high_impact ?? 0} />
          <MetricCard label="Medium" value={summary.medium_impact ?? 0} />
          <MetricCard label="Low" value={summary.low_impact ?? 0} />
        </div>
      ) : (
        <div className="panel">
          <div className="panel-body">
            <div className="empty-state">
              No manifest data. Run <code>drift audit</code> to generate.
            </div>
          </div>
        </div>
      )}

      {/* Full manifest table and attack plan will be added in Phase 3 */}
      <div className="panel">
        <div className="panel-header">
          <h3>Manifest Areas</h3>
          {project.manifest?.areas && (
            <span className="panel-count">
              {project.manifest.areas.length} areas
            </span>
          )}
        </div>
        <div className="panel-body">
          {project.manifest?.areas && project.manifest.areas.length > 0 ? (
            <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>
              {project.manifest.areas.length} drift areas detected.
              Detailed table coming in Phase 3.
            </p>
          ) : (
            <div className="empty-state">No drift areas found.</div>
          )}
        </div>
      </div>

      <div className="panel">
        <div className="panel-header">
          <h3>Attack Plan</h3>
          {project.attackPlan?.plan && (
            <span className="panel-count">
              {project.attackPlan.plan.length} items
            </span>
          )}
        </div>
        <div className="panel-body">
          {project.attackPlan?.plan && project.attackPlan.plan.length > 0 ? (
            <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>
              {project.attackPlan.plan.length} plan items.
              Detailed view coming in Phase 3.
            </p>
          ) : (
            <div className="empty-state">No attack plan. Run <code>drift plan</code> to generate.</div>
          )}
        </div>
      </div>
    </>
  );
}
