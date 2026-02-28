import { Fragment, useEffect, useState } from "react";
import { useDriftStore } from "../data/store";
import { MetricCard, TypeBadge, TimeAgo } from "../components/SharedUI";
import type { LibraryArtifact } from "../types";

// ── Git Status Panel ────────────────────────────────────────────────────

function GitStatusPanel() {
  const gitStatus = useDriftStore((s) => s.gitStatus);
  const gitLoading = useDriftStore((s) => s.gitLoading);
  const gitError = useDriftStore((s) => s.gitError);
  const fetchGitStatus = useDriftStore((s) => s.fetchGitStatus);
  const gitCommit = useDriftStore((s) => s.gitCommit);
  const gitSetRemote = useDriftStore((s) => s.gitSetRemote);
  const gitPush = useDriftStore((s) => s.gitPush);
  const gitPull = useDriftStore((s) => s.gitPull);

  const [remoteInput, setRemoteInput] = useState("");
  const [showRemoteForm, setShowRemoteForm] = useState(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  useEffect(() => {
    fetchGitStatus();
  }, [fetchGitStatus]);

  if (!gitStatus) return null;

  if (!gitStatus.isGitRepo) {
    return (
      <div className="panel">
        <div className="panel-header">
          <h3>Git</h3>
          <span className="badge badge-neutral">No library</span>
        </div>
        <div className="panel-body">
          <span className="text-muted">
            Run <code>drift library init</code> to create the library.
          </span>
        </div>
      </div>
    );
  }

  const handleAction = async (fn: () => Promise<string>) => {
    setActionMessage(null);
    const msg = await fn();
    setActionMessage(msg);
    setTimeout(() => setActionMessage(null), 5000);
  };

  const handleSetRemote = async () => {
    if (!remoteInput.trim()) return;
    await handleAction(() => gitSetRemote(remoteInput.trim()));
    setShowRemoteForm(false);
    setRemoteInput("");
  };

  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Git</h3>
        <div style={{ display: "flex", gap: "var(--sp-2)", alignItems: "center" }}>
          {gitStatus.isDirty && (
            <span className="badge badge-medium">Uncommitted changes</span>
          )}
          {!gitStatus.isDirty && gitStatus.commitCount > 0 && (
            <span className="badge badge-low">Clean</span>
          )}
          {gitStatus.hasRemote && gitStatus.ahead > 0 && (
            <span className="badge badge-accent">{gitStatus.ahead} ahead</span>
          )}
          {gitStatus.hasRemote && gitStatus.behind > 0 && (
            <span className="badge badge-high">{gitStatus.behind} behind</span>
          )}
        </div>
      </div>
      <div className="panel-body">
        <div style={{ marginBottom: "var(--sp-4)", fontSize: 13 }}>
          <span className="text-muted">Remote: </span>
          {gitStatus.hasRemote ? (
            <span className="td-mono">{gitStatus.remoteUrl}</span>
          ) : (
            <span className="text-muted">Not configured</span>
          )}
          <button
            className="btn"
            style={{ marginLeft: "var(--sp-3)" }}
            onClick={() => setShowRemoteForm(!showRemoteForm)}
          >
            {gitStatus.hasRemote ? "Change" : "Set Remote"}
          </button>
        </div>

        {showRemoteForm && (
          <div style={{ display: "flex", gap: "var(--sp-2)", marginBottom: "var(--sp-4)" }}>
            <input
              type="text"
              value={remoteInput}
              onChange={(e) => setRemoteInput(e.target.value)}
              placeholder="https://github.com/org/drift-library.git"
              style={{
                flex: 1,
                background: "var(--bg-elevated)",
                border: "1px solid var(--border-default)",
                borderRadius: "var(--radius-sm)",
                padding: "var(--sp-2) var(--sp-3)",
                color: "var(--text-primary)",
                fontFamily: "var(--font-mono)",
                fontSize: 12,
              }}
              onKeyDown={(e) => e.key === "Enter" && handleSetRemote()}
            />
            <button className="btn btn-accent" onClick={handleSetRemote}>
              Save
            </button>
          </div>
        )}

        <div style={{ display: "flex", gap: "var(--sp-2)" }}>
          <button
            className="btn"
            onClick={() => handleAction(gitCommit)}
            disabled={gitLoading || !gitStatus.isDirty}
          >
            Commit
          </button>
          <button
            className="btn"
            onClick={() => handleAction(gitPush)}
            disabled={gitLoading || !gitStatus.hasRemote}
          >
            Push
          </button>
          <button
            className="btn"
            onClick={() => handleAction(gitPull)}
            disabled={gitLoading || !gitStatus.hasRemote}
          >
            Pull
          </button>
        </div>

        {actionMessage && (
          <div style={{ marginTop: "var(--sp-3)", fontSize: 12, color: "var(--text-secondary)" }}>
            {actionMessage}
          </div>
        )}
        {gitError && (
          <div style={{ marginTop: "var(--sp-3)", fontSize: 12, color: "var(--critical)" }}>
            {gitError}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Library Browser ─────────────────────────────────────────────────────

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

      <GitStatusPanel />

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
                      <Fragment key={artifact.id}>
                        <tr
                          className="detail-row"
                          onClick={() => toggleRow(artifact.id)}
                        >
                          <td className="td-name">{artifact.filename}</td>
                          <td><TypeBadge type={artifact.type} /></td>
                          <td className="td-mono">{artifact.source_project ?? "\u2014"}</td>
                          <td><TimeAgo date={artifact.updated ?? null} /></td>
                        </tr>
                        {isExpanded && (
                          <tr>
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
                      </Fragment>
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
