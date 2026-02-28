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
  SyncBadge,
  VerdictBadge,
} from "../components/SharedUI";
import type { SemanticCluster, CssCluster } from "../types";

// ── Sync Status Panel ────────────────────────────────────────────────────

function SyncStatusPanel({ projectName }: { projectName: string }) {
  const syncStatus = useDriftStore((s) => s.syncStatus);
  const syncLoading = useDriftStore((s) => s.syncLoading);
  const syncError = useDriftStore((s) => s.syncError);
  const fetchSyncStatus = useDriftStore((s) => s.fetchSyncStatus);
  const syncPull = useDriftStore((s) => s.syncPull);
  const syncPush = useDriftStore((s) => s.syncPush);
  const toggleExclude = useDriftStore((s) => s.toggleExclude);

  const [actionMessage, setActionMessage] = useState<string | null>(null);

  useEffect(() => {
    fetchSyncStatus(projectName);
  }, [projectName, fetchSyncStatus]);

  const handleAction = async (fn: () => Promise<string>) => {
    setActionMessage(null);
    const msg = await fn();
    setActionMessage(msg);
    setTimeout(() => setActionMessage(null), 5000);
  };

  const artifacts = syncStatus?.artifacts ?? [];
  const summary = syncStatus?.summary;

  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Library Sync</h3>
        <div style={{ display: "flex", gap: "var(--sp-2)", alignItems: "center" }}>
          <button
            className="btn"
            onClick={() => handleAction(() => syncPull(projectName))}
            disabled={syncLoading}
          >
            Pull
          </button>
          <button
            className="btn"
            onClick={() => handleAction(() => syncPush(projectName))}
            disabled={syncLoading}
          >
            Push
          </button>
        </div>
      </div>

      {summary && summary.total > 0 && (
        <div style={{ padding: "var(--sp-3) var(--sp-4)", borderBottom: "1px solid var(--border-subtle)", display: "flex", gap: "var(--sp-3)", flexWrap: "wrap", fontSize: 13 }}>
          {summary.in_sync > 0 && (
            <span className="badge badge-low">{summary.in_sync} in sync</span>
          )}
          {summary.library_newer > 0 && (
            <span className="badge badge-accent">{summary.library_newer} library newer</span>
          )}
          {summary.project_newer > 0 && (
            <span className="badge badge-medium">{summary.project_newer} project newer</span>
          )}
          {summary.not_synced > 0 && (
            <span className="badge badge-neutral">{summary.not_synced} no mapping</span>
          )}
          {summary.excluded > 0 && (
            <span className="badge badge-neutral">{summary.excluded} excluded</span>
          )}
        </div>
      )}

      <div className="panel-body dense">
        {artifacts.length > 0 ? (
          <table className="data-table">
            <thead>
              <tr>
                <th>Filename</th>
                <th>Type</th>
                <th>Status</th>
                <th style={{ width: 70, textAlign: "center" }}>Exclude</th>
              </tr>
            </thead>
            <tbody>
              {artifacts.map((art) => (
                <tr key={art.id}>
                  <td className="td-name">{art.filename}</td>
                  <td><TypeBadge type={art.type} /></td>
                  <td><SyncBadge status={art.status} /></td>
                  <td style={{ textAlign: "center" }}>
                    <input
                      type="checkbox"
                      checked={art.excluded}
                      onChange={() =>
                        toggleExclude(projectName, art.id, !art.excluded)
                      }
                      disabled={syncLoading}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="empty-state">
            {syncLoading ? "Loading sync status\u2026" : "No library artifacts found."}
          </div>
        )}
      </div>

      {actionMessage && (
        <div style={{ padding: "var(--sp-3) var(--sp-4)", fontSize: 12, color: "var(--text-secondary)", borderTop: "1px solid var(--border-subtle)" }}>
          {actionMessage}
        </div>
      )}
      {syncError && (
        <div style={{ padding: "var(--sp-3) var(--sp-4)", fontSize: 12, color: "var(--critical)", borderTop: "1px solid var(--border-subtle)" }}>
          {syncError}
        </div>
      )}
    </div>
  );
}

// ── Unselected Clusters Panel ─────────────────────────────────────────────

function ClusterRow({
  cluster,
  type,
  isExpanded,
  onToggle,
}: {
  cluster: SemanticCluster | CssCluster;
  type: "semantic" | "css";
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const topSignals = Object.entries(cluster.signalBreakdown ?? {})
    .sort(([, a], [, b]) => b - a)
    .slice(0, 3);

  return (
    <>
      <tr className="detail-row" onClick={onToggle}>
        <td className="td-mono" style={{ fontSize: 12 }}>{cluster.id}</td>
        <td><TypeBadge type={type} /></td>
        <td>
          {type === "semantic"
            ? <VerdictBadge verdict={(cluster as SemanticCluster).verdict} />
            : <span className="badge badge-neutral">--</span>}
        </td>
        <td className="td-mono">{cluster.memberCount}</td>
        <td className="td-mono">{(cluster.avgSimilarity * 100).toFixed(0)}%</td>
      </tr>
      {isExpanded && (
        <tr>
          <td colSpan={5} style={{ padding: 0 }}>
            <div className="detail-expand">
              <div className="detail-label">Members</div>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, lineHeight: 1.8 }}>
                {cluster.members.map((m) => (
                  <div key={m}>{m}</div>
                ))}
              </div>
              {topSignals.length > 0 && (
                <>
                  <div className="detail-label">Top Signals</div>
                  <div style={{ display: "flex", gap: "var(--sp-3)", flexWrap: "wrap" }}>
                    {topSignals.map(([name, val]) => (
                      <span key={name} style={{ fontSize: 12 }}>
                        <span style={{ fontWeight: 500 }}>{name}:</span>{" "}
                        <span className="td-mono">{(val * 100).toFixed(0)}%</span>
                      </span>
                    ))}
                  </div>
                </>
              )}
              {type === "semantic" && (cluster as SemanticCluster).finding && (
                <>
                  {(cluster as SemanticCluster).finding!.role && (
                    <>
                      <div className="detail-label">Role</div>
                      <div>{(cluster as SemanticCluster).finding!.role}</div>
                    </>
                  )}
                  {(cluster as SemanticCluster).finding!.consolidationReasoning && (
                    <>
                      <div className="detail-label">Consolidation Reasoning</div>
                      <div>{(cluster as SemanticCluster).finding!.consolidationReasoning}</div>
                    </>
                  )}
                </>
              )}
              {type === "css" && (cluster as CssCluster).linkedComponents?.length > 0 && (
                <>
                  <div className="detail-label">Linked Components</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--sp-2)" }}>
                    {(cluster as CssCluster).linkedComponents.map((comp) => (
                      <span key={comp} className="badge badge-accent">{comp.split("::").pop()}</span>
                    ))}
                  </div>
                </>
              )}
              {type === "css" && (cluster as CssCluster).sharedCustomProperties?.length > 0 && (
                <>
                  <div className="detail-label">Shared Custom Properties</div>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-secondary)" }}>
                    {(cluster as CssCluster).sharedCustomProperties.join(", ")}
                  </div>
                </>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function UnselectedClustersPanel({ projectName }: { projectName: string }) {
  const clusterData = useDriftStore((s) => s.clusterData);
  const clusterLoading = useDriftStore((s) => s.clusterLoading);
  const clusterError = useDriftStore((s) => s.clusterError);
  const fetchClusters = useDriftStore((s) => s.fetchClusters);
  const [expandedClusters, setExpandedClusters] = useState<Set<string>>(new Set());

  useEffect(() => {
    fetchClusters(projectName);
  }, [projectName, fetchClusters]);

  const toggleCluster = (id: string) => {
    setExpandedClusters((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const semanticUnselected = clusterData?.semantic.unselected ?? [];
  const cssUnselected = clusterData?.css.unselected ?? [];
  const allUnselected: Array<{ cluster: SemanticCluster | CssCluster; type: "semantic" | "css" }> = [
    ...semanticUnselected.map((c) => ({ cluster: c, type: "semantic" as const })),
    ...cssUnselected.map((c) => ({ cluster: c, type: "css" as const })),
  ];

  // Summary counts
  const unverified = semanticUnselected.filter((c) => !c.verdict).length;
  const related = semanticUnselected.filter((c) => c.verdict === "RELATED").length;
  const falsePositive = semanticUnselected.filter((c) => c.verdict === "FALSE_POSITIVE").length;

  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Unselected Clusters</h3>
        {allUnselected.length > 0 && (
          <span className="panel-count">{allUnselected.length} clusters</span>
        )}
      </div>

      {allUnselected.length > 0 && (
        <div style={{ padding: "var(--sp-3) var(--sp-4)", borderBottom: "1px solid var(--border-subtle)", display: "flex", gap: "var(--sp-3)", flexWrap: "wrap", fontSize: 13 }}>
          {unverified > 0 && <span className="badge badge-neutral">{unverified} unverified</span>}
          {related > 0 && <span className="badge badge-low">{related} related</span>}
          {falsePositive > 0 && <span className="badge badge-neutral">{falsePositive} false positive</span>}
          {cssUnselected.length > 0 && <span className="badge badge-medium">{cssUnselected.length} css</span>}
        </div>
      )}

      <div className="panel-body dense">
        {clusterLoading ? (
          <div className="empty-state">Loading clusters&hellip;</div>
        ) : clusterError ? (
          <div className="empty-state" style={{ color: "var(--critical)" }}>{clusterError}</div>
        ) : allUnselected.length > 0 ? (
          <table className="data-table">
            <thead>
              <tr>
                <th>Cluster</th>
                <th>Type</th>
                <th>Verdict</th>
                <th>Members</th>
                <th>Similarity</th>
              </tr>
            </thead>
            <tbody>
              {allUnselected.map(({ cluster, type }) => (
                <ClusterRow
                  key={cluster.id}
                  cluster={cluster}
                  type={type}
                  isExpanded={expandedClusters.has(cluster.id)}
                  onToggle={() => toggleCluster(cluster.id)}
                />
              ))}
            </tbody>
          </table>
        ) : (
          <div className="empty-state">
            {!clusterData
              ? "No pipeline data. Run the semantic pipeline first."
              : "All clusters are in the manifest."}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Project Detail ───────────────────────────────────────────────────────

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
          {summary.by_type && Object.entries(summary.by_type).map(([type, count]) => (
            <MetricCard key={type} label={type} value={count} />
          ))}
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

      <SyncStatusPanel projectName={project.name} />

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
                              {area.type === "css" && area.linked_components && area.linked_components.length > 0 && (
                                <>
                                  <div className="detail-label">Linked Components</div>
                                  <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--sp-2)" }}>
                                    {area.linked_components.map((comp) => (
                                      <span key={comp} className="badge badge-accent">{comp.split("::").pop()}</span>
                                    ))}
                                  </div>
                                </>
                              )}
                              {area.type === "css" && area.shared_custom_properties && area.shared_custom_properties.length > 0 && (
                                <>
                                  <div className="detail-label">Shared Custom Properties</div>
                                  <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-secondary)" }}>
                                    {area.shared_custom_properties.join(", ")}
                                  </div>
                                </>
                              )}
                              {area.type === "semantic" && area.semantic_role && (
                                <>
                                  <div className="detail-label">Semantic Role</div>
                                  <div>{area.semantic_role}</div>
                                </>
                              )}
                              {area.type === "semantic" && area.consolidation_assessment && (
                                <>
                                  <div className="detail-label">Consolidation Assessment</div>
                                  <div>{area.consolidation_assessment}</div>
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

      <UnselectedClustersPanel projectName={project.name} />

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
