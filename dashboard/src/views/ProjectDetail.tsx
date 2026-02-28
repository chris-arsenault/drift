import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { useDriftStore } from "../data/store";
import {
  StalenessBadge,
  ModeBadge,
  MetricCard,
  TypeBadge,
  ImpactBadge,
  PhaseBadge,
} from "../components/SharedUI";

export default function ProjectDetail() {
  const { name } = useParams<{ name: string }>();
  const fetchProject = useDriftStore((s) => s.fetchProject);
  const project = useDriftStore((s) => s.selectedProject);
  const loading = useDriftStore((s) => s.loading);
  const error = useDriftStore((s) => s.error);

  const [expandedAreas, setExpandedAreas] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (name) fetchProject(name);
  }, [name, fetchProject]);

  const toggleArea = (id: string) => {
    setExpandedAreas((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

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
  const areas = project.manifest?.areas ?? [];
  const plan = project.attackPlan?.plan ?? [];

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

      <div className="panel">
        <div className="panel-header">
          <h3>Manifest Areas</h3>
          {areas.length > 0 && (
            <span className="panel-count">
              {areas.length} areas
            </span>
          )}
        </div>
        <div className="panel-body dense">
          {areas.length > 0 ? (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Type</th>
                  <th>Impact</th>
                  <th>Files</th>
                </tr>
              </thead>
              <tbody>
                {areas.map((area) => {
                  const isExpanded = expandedAreas.has(area.id);
                  return (
                    <>
                      <tr
                        key={area.id}
                        className="detail-row"
                        onClick={() => toggleArea(area.id)}
                      >
                        <td className="td-name">{area.name}</td>
                        <td><TypeBadge type={area.type} /></td>
                        <td><ImpactBadge impact={area.impact} /></td>
                        <td className="td-mono">{area.total_files}</td>
                      </tr>
                      {isExpanded && (
                        <tr key={`${area.id}-detail`}>
                          <td colSpan={4} style={{ padding: 0 }}>
                            <div className="detail-expand">
                              <div className="detail-label">Analysis</div>
                              <div>{area.analysis}</div>
                              <div className="detail-label">Recommendation</div>
                              <div>{area.recommendation}</div>
                              {area.variants.length > 0 && (
                                <>
                                  <div className="detail-label">Variants</div>
                                  <div>
                                    {area.variants.map((v) => (
                                      <div key={v.name} style={{ marginBottom: "var(--sp-1)" }}>
                                        <span style={{ fontWeight: 500 }}>{v.name}</span>
                                        <span className="td-mono" style={{ marginLeft: "var(--sp-2)", color: "var(--text-secondary)" }}>
                                          {v.file_count} files
                                        </span>
                                      </div>
                                    ))}
                                  </div>
                                </>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </>
                  );
                })}
              </tbody>
            </table>
          ) : (
            <div className="empty-state">No drift areas found.</div>
          )}
        </div>
      </div>

      <div className="panel">
        <div className="panel-header">
          <h3>Attack Plan</h3>
          {plan.length > 0 && (
            <span className="panel-count">
              {plan.length} items
            </span>
          )}
        </div>
        <div className="panel-body">
          {plan.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: "var(--sp-3)" }}>
              {plan.map((item, i) => {
                const entries = Object.entries(item).filter(
                  ([k]) => k !== "phase"
                );
                return (
                  <div
                    key={i}
                    style={{
                      border: "1px solid var(--border-subtle)",
                      borderRadius: "var(--radius-md)",
                      padding: "var(--sp-4)",
                      background: "var(--bg-elevated)",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: "var(--sp-3)", marginBottom: entries.length > 0 ? "var(--sp-2)" : 0 }}>
                      {item.phase && <PhaseBadge phase={item.phase} />}
                      <span style={{ fontWeight: 500 }}>Item {i + 1}</span>
                    </div>
                    {entries.length > 0 && (
                      <div style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.6 }}>
                        {entries.map(([key, value]) => (
                          <div key={key}>
                            <span style={{ fontWeight: 500, color: "var(--text-primary)" }}>{key}: </span>
                            {typeof value === "string" ? value : JSON.stringify(value)}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="empty-state">No attack plan. Run <code>drift plan</code> to generate.</div>
          )}
        </div>
      </div>
    </>
  );
}
