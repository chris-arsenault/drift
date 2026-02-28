import type { Staleness, PlanProgress, SyncState } from "../types";

// ── Impact Badge ────────────────────────────────────────────────────────

const IMPACT_CLASS: Record<string, string> = {
  HIGH: "badge-high",
  MEDIUM: "badge-medium",
  LOW: "badge-low",
};

export function ImpactBadge({ impact }: { impact: string }) {
  return (
    <span className={`badge ${IMPACT_CLASS[impact] ?? "badge-neutral"}`}>
      {impact}
    </span>
  );
}

// ── Staleness Badge ─────────────────────────────────────────────────────

const STALENESS_CLASS: Record<Staleness, string> = {
  fresh: "badge-low",
  stale: "badge-medium",
  outdated: "badge-high",
  "no-manifest": "badge-neutral",
};

const STALENESS_LABEL: Record<Staleness, string> = {
  fresh: "Fresh",
  stale: "Stale",
  outdated: "Outdated",
  "no-manifest": "No manifest",
};

export function StalenessBadge({ staleness }: { staleness: Staleness }) {
  return (
    <span className={`badge ${STALENESS_CLASS[staleness]}`}>
      {STALENESS_LABEL[staleness]}
    </span>
  );
}

// ── Phase Badge ─────────────────────────────────────────────────────────

const PHASE_CLASS: Record<string, string> = {
  completed: "badge-low",
  in_progress: "badge-accent",
  pending: "badge-neutral",
  planned: "badge-neutral",
};

export function PhaseBadge({ phase }: { phase: string }) {
  return (
    <span className={`badge ${PHASE_CLASS[phase] ?? "badge-neutral"}`}>
      {phase.replace(/_/g, " ")}
    </span>
  );
}

// ── Type Badge ──────────────────────────────────────────────────────────

const TYPE_CLASS: Record<string, string> = {
  // Cluster finding types
  structural: "badge-accent",
  behavioral: "badge-high",
  semantic: "badge-low",
  css: "badge-medium",
  // Library artifact types
  "eslint-rule": "badge-accent",
  adr: "badge-medium",
  pattern: "badge-low",
  checklist: "badge-neutral",
  "ast-grep-rule": "badge-accent",
  "ruff-rule": "badge-accent",
};

export function TypeBadge({ type }: { type: string }) {
  return (
    <span className={`badge ${TYPE_CLASS[type] ?? "badge-neutral"}`}>
      {type}
    </span>
  );
}

// ── Verdict Badge ──────────────────────────────────────────────────────

const VERDICT_CLASS: Record<string, string> = {
  DUPLICATE: "badge-high",
  OVERLAPPING: "badge-medium",
  RELATED: "badge-low",
  FALSE_POSITIVE: "badge-neutral",
};

export function VerdictBadge({ verdict }: { verdict: string | null }) {
  if (!verdict) return <span className="badge badge-neutral">Unverified</span>;
  return (
    <span className={`badge ${VERDICT_CLASS[verdict] ?? "badge-neutral"}`}>
      {verdict}
    </span>
  );
}

// ── Sync Badge ─────────────────────────────────────────────────────────

const SYNC_CLASS: Record<SyncState, string> = {
  in_sync: "badge-low",
  library_newer: "badge-accent",
  project_newer: "badge-medium",
  not_synced: "badge-neutral",
  excluded: "badge-neutral",
};

const SYNC_LABEL: Record<SyncState, string> = {
  in_sync: "In sync",
  library_newer: "Library newer",
  project_newer: "Project newer",
  not_synced: "No mapping",
  excluded: "Excluded",
};

export function SyncBadge({ status }: { status: SyncState }) {
  return (
    <span className={`badge ${SYNC_CLASS[status]}`}>
      {SYNC_LABEL[status]}
    </span>
  );
}

// ── Mode Badge ──────────────────────────────────────────────────────────

export function ModeBadge({ mode }: { mode: string | null }) {
  if (!mode) return null;
  const cls = mode === "online" ? "badge-accent" : "badge-neutral";
  return <span className={`badge ${cls}`}>{mode}</span>;
}

// ── Progress Bar ────────────────────────────────────────────────────────

export function ProgressBar({ progress }: { progress: PlanProgress }) {
  if (progress.total === 0) {
    return (
      <div className="progress-bar-container">
        <div className="progress-bar">
          <div className="progress-bar-fill" style={{ width: 0 }} />
        </div>
        <span className="progress-bar-label">No plan</span>
      </div>
    );
  }
  const pct = Math.round((progress.completed / progress.total) * 100);
  return (
    <div className="progress-bar-container">
      <div className="progress-bar">
        <div className="progress-bar-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="progress-bar-label">
        {progress.completed}/{progress.total}
      </span>
    </div>
  );
}

// ── Metric Card ─────────────────────────────────────────────────────────

export function MetricCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string | number;
  sub?: string;
}) {
  return (
    <div className="metric-card">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      {sub && <div className="metric-sub">{sub}</div>}
    </div>
  );
}

// ── TimeAgo ─────────────────────────────────────────────────────────────

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

export function TimeAgo({ date }: { date: string | null }) {
  if (!date) return <span className="text-muted">Never</span>;

  const ms = Date.now() - new Date(date).getTime();
  let label: string;

  if (ms < MINUTE) label = "Just now";
  else if (ms < HOUR) label = `${Math.floor(ms / MINUTE)}m ago`;
  else if (ms < DAY) label = `${Math.floor(ms / HOUR)}h ago`;
  else label = `${Math.floor(ms / DAY)}d ago`;

  return <span title={date}>{label}</span>;
}
