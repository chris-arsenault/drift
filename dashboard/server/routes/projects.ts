import path from "node:path";
import fs from "node:fs/promises";
import crypto from "node:crypto";
import os from "node:os";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { Router } from "express";
import {
  readRegistry,
  readJsonSafe,
  computeStaleness,
  computePlanProgress,
} from "../registry.js";
import type { PlanProgress, Staleness } from "../registry.js";

const execFileAsync = promisify(execFile);
const LIBRARY_DIR = path.join(os.homedir(), ".drift", "library");
const LIBRARY_PATH = path.join(LIBRARY_DIR, "library.json");
const SUBSCRIPTIONS_PATH = path.join(LIBRARY_DIR, "subscriptions.json");
const SCRIPTS_DIR = path.resolve(import.meta.dirname, "..", "..", "..", "scripts");

export const projectsRouter = Router();

// ── Types ──────────────────────────────────────────────────────────────

interface ManifestSummary {
  total_drift_areas?: number;
  total_files_affected?: number;
  high_impact?: number;
  medium_impact?: number;
  low_impact?: number;
  by_type?: Record<string, number>;
}

interface Manifest {
  generated?: string;
  project_name?: string;
  summary?: ManifestSummary;
  [key: string]: unknown;
}

interface Config {
  mode?: string;
  [key: string]: unknown;
}

interface AttackPlan {
  plan?: Array<{ phase?: string; [key: string]: unknown }>;
  [key: string]: unknown;
}

interface LibraryArtifact {
  id: string;
  type: string;
  filename: string;
  source_project?: string;
  checksum?: string;
  path: string;
  [key: string]: unknown;
}

interface Library {
  version: number;
  artifacts: LibraryArtifact[];
}

interface Subscriptions {
  version: number;
  projects: Record<string, { exclude: string[] }>;
}

// ── Sync helpers ────────────────────────────────────────────────────────

const TYPE_DIRS: Record<string, string> = {
  "eslint-rule": "rules/eslint",
  "ruff-rule": "rules/ruff",
  "ast-grep-rule": "rules/ast-grep",
  adr: "adr",
  pattern: "patterns",
  checklist: "checklists",
};

type SyncState =
  | "in_sync"
  | "library_newer"
  | "project_newer"
  | "not_synced"
  | "excluded";

async function sha256File(filePath: string): Promise<string> {
  const data = await fs.readFile(filePath);
  const hash = crypto.createHash("sha256").update(data).digest("hex");
  return `sha256:${hash}`;
}

async function loadSubscriptions(): Promise<Subscriptions> {
  const data = await readJsonSafe<Subscriptions>(SUBSCRIPTIONS_PATH);
  return data ?? { version: 1, projects: {} };
}

async function saveSubscriptions(subs: Subscriptions): Promise<void> {
  await fs.writeFile(SUBSCRIPTIONS_PATH, JSON.stringify(subs, null, 2) + "\n");
}

function findProject(registry: { projects: Array<{ name: string; path: string; lastRun: string | null }> }, name: string) {
  return registry.projects.find((p) => path.basename(p.path) === name);
}

interface ProjectListItem {
  name: string;
  path: string;
  lastRun: string | null;
  staleness: Staleness;
  mode: string | null;
  summary: ManifestSummary | null;
  planProgress: PlanProgress;
}

// ── GET / — List all projects ──────────────────────────────────────────

projectsRouter.get("/", async (_req, res) => {
  const registry = await readRegistry();
  const results: ProjectListItem[] = [];

  for (const project of registry.projects) {
    const auditDir = path.join(project.path, ".drift-audit");

    const manifest = await readJsonSafe<Manifest>(
      path.join(auditDir, "drift-manifest.json"),
    );
    const attackPlan = await readJsonSafe<AttackPlan>(
      path.join(auditDir, "attack-plan.json"),
    );
    const config = await readJsonSafe<Config>(
      path.join(auditDir, "config.json"),
    );

    results.push({
      name: project.name,
      path: project.path,
      lastRun: manifest?.generated ?? project.lastRun,
      staleness: computeStaleness(manifest?.generated ?? project.lastRun),
      mode: config?.mode ?? null,
      summary: manifest?.summary ?? null,
      planProgress: computePlanProgress(attackPlan),
    });
  }

  res.json({ projects: results });
});

// ── GET /:name — Single project detail ─────────────────────────────────

projectsRouter.get("/:name", async (req, res) => {
  const registry = await readRegistry();
  const project = registry.projects.find(
    (p) => path.basename(p.path) === req.params.name,
  );

  if (!project) {
    res.status(404).json({ error: `Project "${req.params.name}" not found` });
    return;
  }

  const auditDir = path.join(project.path, ".drift-audit");

  const manifest = await readJsonSafe<Manifest>(
    path.join(auditDir, "drift-manifest.json"),
  );
  const attackPlan = await readJsonSafe<AttackPlan>(
    path.join(auditDir, "attack-plan.json"),
  );
  const config = await readJsonSafe<Config>(
    path.join(auditDir, "config.json"),
  );

  res.json({
    name: project.name,
    path: project.path,
    lastRun: manifest?.generated ?? project.lastRun,
    staleness: computeStaleness(manifest?.generated ?? project.lastRun),
    manifest,
    attackPlan,
    config,
  });
});

// ── GET /:name/sync — Artifact sync status ──────────────────────────────

projectsRouter.get("/:name/sync", async (req, res) => {
  const registry = await readRegistry();
  const project = findProject(registry, req.params.name);

  if (!project) {
    res.status(404).json({ error: `Project "${req.params.name}" not found` });
    return;
  }

  const library = await readJsonSafe<Library>(LIBRARY_PATH);
  if (!library) {
    res.json({ project: project.name, artifacts: [], summary: { in_sync: 0, library_newer: 0, project_newer: 0, not_synced: 0, excluded: 0, total: 0 } });
    return;
  }

  const config = await readJsonSafe<Config>(
    path.join(project.path, ".drift-audit", "config.json"),
  );
  const syncMap: Record<string, string> = (config as Record<string, unknown>)?.sync as Record<string, string> ?? {};
  const subs = await loadSubscriptions();
  const excludeSet = new Set(subs.projects[project.name]?.exclude ?? []);

  const artifacts: Array<{
    id: string;
    type: string;
    filename: string;
    source_project: string | null;
    status: SyncState;
    excluded: boolean;
  }> = [];

  for (const art of library.artifacts) {
    const excluded = excludeSet.has(art.id);

    if (excluded) {
      artifacts.push({
        id: art.id,
        type: art.type,
        filename: art.filename,
        source_project: art.source_project ?? null,
        status: "excluded",
        excluded: true,
      });
      continue;
    }

    if (!(art.type in syncMap)) {
      artifacts.push({
        id: art.id,
        type: art.type,
        filename: art.filename,
        source_project: art.source_project ?? null,
        status: "not_synced",
        excluded: false,
      });
      continue;
    }

    const localDir = path.join(project.path, syncMap[art.type]);
    const localPath = path.join(localDir, art.filename);

    let status: SyncState;
    try {
      const localChecksum = await sha256File(localPath);
      if (localChecksum === art.checksum) {
        status = "in_sync";
      } else {
        // Compare mtimes to infer direction
        const [localStat, libStat] = await Promise.all([
          fs.stat(localPath),
          fs.stat(path.join(LIBRARY_DIR, TYPE_DIRS[art.type] ?? "", art.filename)).catch(() => null),
        ]);
        status = libStat && libStat.mtimeMs > localStat.mtimeMs
          ? "library_newer"
          : "project_newer";
      }
    } catch {
      status = "library_newer"; // local file doesn't exist
    }

    artifacts.push({
      id: art.id,
      type: art.type,
      filename: art.filename,
      source_project: art.source_project ?? null,
      status,
      excluded: false,
    });
  }

  const summary = {
    in_sync: artifacts.filter((a) => a.status === "in_sync").length,
    library_newer: artifacts.filter((a) => a.status === "library_newer").length,
    project_newer: artifacts.filter((a) => a.status === "project_newer").length,
    not_synced: artifacts.filter((a) => a.status === "not_synced").length,
    excluded: artifacts.filter((a) => a.status === "excluded").length,
    total: artifacts.length,
  };

  res.json({ project: project.name, artifacts, summary });
});

// ── GET /:name/clusters — Pipeline cluster data with selection status ────

interface ClusterEntry {
  id: string;
  members: string[];
  memberCount: number;
  avgSimilarity: number;
  signalBreakdown: Record<string, number>;
  directorySpread: number;
  rankScore: number;
  [key: string]: unknown;
}

interface Finding {
  clusterId: string;
  verdict: string;
  confidence?: string;
  role?: string;
  sharedBehavior?: string;
  consolidationReasoning?: string;
  consolidationComplexity?: string;
  [key: string]: unknown;
}

interface ManifestArea {
  id: string;
  [key: string]: unknown;
}

projectsRouter.get("/:name/clusters", async (req, res) => {
  const registry = await readRegistry();
  const project = findProject(registry, req.params.name);

  if (!project) {
    res.status(404).json({ error: `Project "${req.params.name}" not found` });
    return;
  }

  const auditDir = path.join(project.path, ".drift-audit");
  const semanticDir = path.join(auditDir, "semantic");

  const [clusters, findings, cssClusters, manifest] = await Promise.all([
    readJsonSafe<ClusterEntry[]>(path.join(semanticDir, "clusters.json")),
    readJsonSafe<Finding[]>(path.join(semanticDir, "findings.json")),
    readJsonSafe<ClusterEntry[]>(path.join(semanticDir, "css-clusters.json")),
    readJsonSafe<Manifest & { areas?: ManifestArea[] }>(
      path.join(auditDir, "drift-manifest.json"),
    ),
  ]);

  // Build findings lookup
  const findingsByCluster: Record<string, Finding> = {};
  for (const f of findings ?? []) {
    if (f.clusterId) findingsByCluster[f.clusterId] = f;
  }

  // Build manifest area ID set
  const manifestIds = new Set(
    (manifest?.areas ?? []).map((a) => a.id),
  );

  // Classify semantic clusters
  const semanticSelected: Array<ClusterEntry & { finding: Finding | null; verdict: string | null; inManifest: true }> = [];
  const semanticUnselected: Array<ClusterEntry & { finding: Finding | null; verdict: string | null; inManifest: false }> = [];

  for (const c of clusters ?? []) {
    const finding = findingsByCluster[c.id] ?? null;
    const inManifest = manifestIds.has(`semantic-${c.id}`);
    if (inManifest) {
      semanticSelected.push({ ...c, finding, verdict: finding?.verdict ?? null, inManifest: true });
    } else {
      semanticUnselected.push({ ...c, finding, verdict: finding?.verdict ?? null, inManifest: false });
    }
  }

  // Classify CSS clusters
  const cssSelected: Array<ClusterEntry & { inManifest: true }> = [];
  const cssUnselected: Array<ClusterEntry & { inManifest: false }> = [];

  for (const c of cssClusters ?? []) {
    const inManifest = manifestIds.has(`css-${c.id}`);
    if (inManifest) {
      cssSelected.push({ ...c, inManifest: true });
    } else {
      cssUnselected.push({ ...c, inManifest: false });
    }
  }

  res.json({
    semantic: {
      selected: semanticSelected,
      unselected: semanticUnselected,
      total: (clusters ?? []).length,
    },
    css: {
      selected: cssSelected,
      unselected: cssUnselected,
      total: (cssClusters ?? []).length,
    },
  });
});

// ── POST /:name/sync/pull — Pull artifacts from library ─────────────────

projectsRouter.post("/:name/sync/pull", async (req, res) => {
  const registry = await readRegistry();
  const project = findProject(registry, req.params.name);

  if (!project) {
    res.status(404).json({ error: `Project "${req.params.name}" not found` });
    return;
  }

  const configPath = path.join(project.path, ".drift-audit", "config.json");
  try {
    await fs.access(configPath);
  } catch {
    res.status(400).json({ error: "Project has no .drift-audit/config.json" });
    return;
  }

  try {
    const script = path.join(SCRIPTS_DIR, "library-pull.py");
    const { stderr } = await execFileAsync("python3", [script, configPath]);
    res.json({ message: stderr.trim() || "Pull complete" });
  } catch (err) {
    const msg = (err as { stderr?: string }).stderr || (err as Error).message;
    res.status(500).json({ error: `Pull failed: ${msg}` });
  }
});

// ── POST /:name/sync/push — Push artifacts to library ────────────────────

projectsRouter.post("/:name/sync/push", async (req, res) => {
  const registry = await readRegistry();
  const project = findProject(registry, req.params.name);

  if (!project) {
    res.status(404).json({ error: `Project "${req.params.name}" not found` });
    return;
  }

  const configPath = path.join(project.path, ".drift-audit", "config.json");
  try {
    await fs.access(configPath);
  } catch {
    res.status(400).json({ error: "Project has no .drift-audit/config.json" });
    return;
  }

  try {
    const script = path.join(SCRIPTS_DIR, "library-push.py");
    const { stderr } = await execFileAsync("python3", [script, configPath]);
    res.json({ message: stderr.trim() || "Push complete" });
  } catch (err) {
    const msg = (err as { stderr?: string }).stderr || (err as Error).message;
    res.status(500).json({ error: `Push failed: ${msg}` });
  }
});

// ── POST /:name/sync/exclude — Toggle artifact exclude ───────────────────

projectsRouter.post("/:name/sync/exclude", async (req, res) => {
  const registry = await readRegistry();
  const project = findProject(registry, req.params.name);

  if (!project) {
    res.status(404).json({ error: `Project "${req.params.name}" not found` });
    return;
  }

  const { artifactId, excluded } = req.body as {
    artifactId?: string;
    excluded?: boolean;
  };

  if (!artifactId || typeof excluded !== "boolean") {
    res.status(400).json({ error: "Missing artifactId or excluded in body" });
    return;
  }

  const subs = await loadSubscriptions();
  if (!subs.projects[project.name]) {
    subs.projects[project.name] = { exclude: [] };
  }

  const excludeList = subs.projects[project.name].exclude;
  const idx = excludeList.indexOf(artifactId);

  if (excluded && idx === -1) {
    excludeList.push(artifactId);
  } else if (!excluded && idx !== -1) {
    excludeList.splice(idx, 1);
  }

  await saveSubscriptions(subs);
  res.json({ message: `${artifactId} ${excluded ? "excluded" : "included"}` });
});
