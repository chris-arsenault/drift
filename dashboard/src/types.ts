// ── Staleness & Progress ────────────────────────────────────────────────

export type Staleness = "fresh" | "stale" | "outdated" | "no-manifest";

export interface PlanProgress {
  completed: number;
  in_progress: number;
  pending: number;
  total: number;
}

// ── Manifest ────────────────────────────────────────────────────────────

export interface ManifestSummary {
  total_drift_areas?: number;
  total_files_affected?: number;
  high_impact?: number;
  medium_impact?: number;
  low_impact?: number;
  by_type?: Record<string, number>;
}

export interface Variant {
  name: string;
  description: string;
  file_count: number;
  files: string[];
  sample_file: string;
}

export interface DriftArea {
  id: string;
  name: string;
  type: string;
  description: string;
  impact: "HIGH" | "MEDIUM" | "LOW";
  total_files: number;
  variants: Variant[];
  semantic_role?: string | null;
  consolidation_assessment?: string | null;
  linked_components?: string[];
  shared_custom_properties?: string[];
  analysis: string;
  recommendation: string;
  status: string;
}

export interface ManifestData {
  generated?: string;
  project_name?: string;
  summary?: ManifestSummary;
  areas?: DriftArea[];
  [key: string]: unknown;
}

// ── Attack Plan ─────────────────────────────────────────────────────────

export interface PlanItem {
  phase?: string;
  [key: string]: unknown;
}

export interface AttackPlanData {
  plan?: PlanItem[];
  [key: string]: unknown;
}

// ── Merge Records ───────────────────────────────────────────────────────

export interface MergeRecord {
  area_id: string;
  merged_at: string;
  [key: string]: unknown;
}

// ── Project Config ──────────────────────────────────────────────────────

export interface ProjectConfig {
  mode?: string;
  [key: string]: unknown;
}

// ── Projects API ────────────────────────────────────────────────────────

/** Shape returned by GET /api/projects (list item) */
export interface ProjectSummary {
  name: string;
  path: string;
  lastRun: string | null;
  staleness: Staleness;
  mode: string | null;
  summary: ManifestSummary | null;
  planProgress: PlanProgress;
}

/** Shape returned by GET /api/projects/:name */
export interface ProjectDetail {
  name: string;
  path: string;
  lastRun: string | null;
  staleness: Staleness;
  manifest: ManifestData | null;
  attackPlan: AttackPlanData | null;
  config: ProjectConfig | null;
}

// ── Library API ─────────────────────────────────────────────────────────

export interface LibraryArtifact {
  id: string;
  type: string;
  filename: string;
  source_project?: string;
  created?: string;
  updated?: string;
  description?: string;
  checksum?: string;
  path: string;
}

export interface LibraryData {
  library: { version: number; artifacts: LibraryArtifact[] } | null;
  stats: {
    total: number;
    byType: Record<string, number>;
  };
}

export interface ArtifactDetail {
  artifact: LibraryArtifact;
  content: string | null;
}

// ── Library Git Status ──────────────────────────────────────────────────

export interface LibraryGitStatus {
  isGitRepo: boolean;
  hasRemote: boolean;
  remoteUrl: string | null;
  branch: string | null;
  isDirty: boolean;
  commitCount: number;
  ahead: number;
  behind: number;
}

// ── Sync Status ─────────────────────────────────────────────────────────

export type SyncState =
  | "in_sync"
  | "library_newer"
  | "project_newer"
  | "not_synced"
  | "excluded";

export interface ArtifactSyncStatus {
  id: string;
  type: string;
  filename: string;
  source_project: string | null;
  status: SyncState;
  excluded: boolean;
}

export interface ProjectSyncSummary {
  in_sync: number;
  library_newer: number;
  project_newer: number;
  not_synced: number;
  excluded: number;
  total: number;
}

export interface ProjectSyncStatus {
  project: string;
  artifacts: ArtifactSyncStatus[];
  summary: ProjectSyncSummary;
}
