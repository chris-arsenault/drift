import { useEffect } from "react";
import { useDriftStore } from "../data/store";
import { MetricCard } from "../components/SharedUI";

export default function LibraryBrowser() {
  const fetchLibrary = useDriftStore((s) => s.fetchLibrary);
  const library = useDriftStore((s) => s.library);
  const loading = useDriftStore((s) => s.loading);
  const error = useDriftStore((s) => s.error);

  useEffect(() => {
    fetchLibrary();
  }, [fetchLibrary]);

  if (loading) {
    return (
      <div className="api-gate">
        <div className="api-gate-spinner" />
        <p>Loading library&hellip;</p>
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

  const stats = library?.stats;
  const byType = stats?.byType ?? {};

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

      {/* Full artifact table will be added in Phase 3 */}
      <div className="panel">
        <div className="panel-header">
          <h3>Artifacts</h3>
          {stats && <span className="panel-count">{stats.total} total</span>}
        </div>
        <div className="panel-body">
          {stats && stats.total > 0 ? (
            <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>
              {stats.total} artifacts in library.
              Detailed table coming in Phase 3.
            </p>
          ) : (
            <div className="empty-state">
              Library is empty. Run <code>drift library push</code> from a
              project to share artifacts.
            </div>
          )}
        </div>
      </div>
    </>
  );
}
