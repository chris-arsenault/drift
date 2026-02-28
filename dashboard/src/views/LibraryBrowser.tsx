import { useEffect, useState } from "react";
import { useDriftStore } from "../data/store";
import { MetricCard, TypeBadge, TimeAgo } from "../components/SharedUI";
import type { LibraryArtifact } from "../types";

export default function LibraryBrowser() {
  const fetchLibrary = useDriftStore((s) => s.fetchLibrary);
  const library = useDriftStore((s) => s.library);
  const loading = useDriftStore((s) => s.loading);
  const error = useDriftStore((s) => s.error);
  const fetchArtifact = useDriftStore((s) => s.fetchArtifact);
  const selectedArtifact = useDriftStore((s) => s.selectedArtifact);

  const [typeFilter, setTypeFilter] = useState<string>("All");
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [loadingArtifactId, setLoadingArtifactId] = useState<string | null>(null);

  useEffect(() => {
    fetchLibrary();
  }, [fetchLibrary]);

  const toggleRow = (id: string) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleFetchContent = async (id: string) => {
    setLoadingArtifactId(id);
    await fetchArtifact(id);
    setLoadingArtifactId(null);
  };

  if (loading && !library) {
    return (
      <div className="api-gate">
        <div className="api-gate-spinner" />
        <p>Loading library&hellip;</p>
      </div>
    );
  }

  if (error && !library) {
    return (
      <div className="api-gate">
        <h2>Error</h2>
        <p>{error}</p>
      </div>
    );
  }

  const stats = library?.stats;
  const byType = stats?.byType ?? {};
  const artifacts: LibraryArtifact[] = library?.library?.artifacts ?? [];
  const types = Object.keys(byType);

  const filtered =
    typeFilter === "All"
      ? artifacts
      : artifacts.filter((a) => a.type === typeFilter);

  return (
    <>
      <div className="view-header">
        <h2>Library</h2>
        <div className="view-desc">
          Shared artifacts across all drift projects.
        </div>
      </div>

      <div className="metrics-row">
        <MetricCard label="Total Artifacts" value={stats?.total ?? 0} />
        {Object.entries(byType).map(([type, count]) => (
          <MetricCard key={type} label={type} value={count} />
        ))}
      </div>

      <div className="panel">
        <div className="panel-header">
          <h3>Artifacts</h3>
          {stats && <span className="panel-count">{stats.total} total</span>}
        </div>

        {artifacts.length > 0 ? (
          <>
            <div style={{ padding: "var(--sp-3) var(--sp-4)", borderBottom: "1px solid var(--border-subtle)", display: "flex", gap: "var(--sp-2)", flexWrap: "wrap" }}>
              <button
                className={`btn ${typeFilter === "All" ? "btn-accent" : ""}`}
                onClick={() => setTypeFilter("All")}
              >
                All
              </button>
              {types.map((type) => (
                <button
                  key={type}
                  className={`btn ${typeFilter === type ? "btn-accent" : ""}`}
                  onClick={() => setTypeFilter(type)}
                >
                  {type}
                </button>
              ))}
            </div>

            <div className="panel-body dense">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Filename</th>
                    <th>Type</th>
                    <th>Source</th>
                    <th>Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((artifact) => {
                    const isExpanded = expandedRows.has(artifact.id);
                    const isSelected =
                      selectedArtifact?.artifact.id === artifact.id;
                    return (
                      <>
                        <tr
                          key={artifact.id}
                          className="detail-row"
                          onClick={() => toggleRow(artifact.id)}
                        >
                          <td className="td-name">{artifact.filename}</td>
                          <td><TypeBadge type={artifact.type} /></td>
                          <td className="td-mono">{artifact.source_project ?? "\u2014"}</td>
                          <td><TimeAgo date={artifact.updated ?? null} /></td>
                        </tr>
                        {isExpanded && (
                          <tr key={`${artifact.id}-detail`}>
                            <td colSpan={4} style={{ padding: 0 }}>
                              <div className="detail-expand">
                                {artifact.description && (
                                  <>
                                    <div className="detail-label">Description</div>
                                    <div>{artifact.description}</div>
                                  </>
                                )}
                                <div className="detail-label">ID</div>
                                <div className="td-mono">{artifact.id}</div>
                                <div style={{ marginTop: "var(--sp-3)" }}>
                                  {isSelected && selectedArtifact?.content != null ? (
                                    <>
                                      <div className="detail-label">Content</div>
                                      <pre
                                        style={{
                                          fontFamily: "var(--font-mono)",
                                          fontSize: 12,
                                          whiteSpace: "pre-wrap",
                                          maxHeight: 400,
                                          overflowY: "auto",
                                        }}
                                      >
                                        {selectedArtifact.content}
                                      </pre>
                                    </>
                                  ) : (
                                    <button
                                      className="btn"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        handleFetchContent(artifact.id);
                                      }}
                                      disabled={loadingArtifactId === artifact.id}
                                    >
                                      {loadingArtifactId === artifact.id
                                        ? "Loading..."
                                        : "View Content"}
                                    </button>
                                  )}
                                </div>
                              </div>
                            </td>
                          </tr>
                        )}
                      </>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <div className="panel-body">
            <div className="empty-state">
              Library is empty. Run <code>drift library push</code> from a
              project to share artifacts.
            </div>
          </div>
        )}
      </div>
    </>
  );
}
