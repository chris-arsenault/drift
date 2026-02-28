import fs from "node:fs/promises";
import path from "node:path";
import os from "node:os";

// ── Types ──────────────────────────────────────────────────────────────

export interface RegistryProject {
  path: string;
  name: string;
  added: string;
  lastRun: string | null;
}

export interface Registry {
  version: 1;
  projects: RegistryProject[];
}

export type Staleness = "fresh" | "stale" | "outdated" | "no-manifest";

export interface PlanProgress {
  completed: number;
  in_progress: number;
  pending: number;
  total: number;
}

// ── Paths ──────────────────────────────────────────────────────────────

const DRIFT_DIR = path.join(os.homedir(), ".drift");
const REGISTRY_PATH = path.join(DRIFT_DIR, "registry.json");
const SRC_DIR = path.join(os.homedir(), "src");

// ── Helpers ────────────────────────────────────────────────────────────

export async function readJsonSafe<T = unknown>(
  filePath: string,
): Promise<T | null> {
  try {
    const raw = await fs.readFile(filePath, "utf-8");
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

// ── Discovery ──────────────────────────────────────────────────────────

export async function discoverProjects(): Promise<RegistryProject[]> {
  const projects: RegistryProject[] = [];

  let entries: string[];
  try {
    entries = await fs.readdir(SRC_DIR);
  } catch {
    return projects;
  }

  for (const entry of entries) {
    const projectPath = path.join(SRC_DIR, entry);
    const configPath = path.join(projectPath, ".drift-audit", "config.json");
    const config = await readJsonSafe<Record<string, unknown>>(configPath);
    if (!config) continue;

    const manifestPath = path.join(
      projectPath,
      ".drift-audit",
      "drift-manifest.json",
    );
    const manifest =
      await readJsonSafe<Record<string, unknown>>(manifestPath);

    projects.push({
      path: projectPath,
      name: entry,
      added: new Date().toISOString(),
      lastRun: (manifest?.generated as string) ?? null,
    });
  }

  return projects;
}

// ── Registry I/O ───────────────────────────────────────────────────────

export async function readRegistry(): Promise<Registry> {
  const existing = await readJsonSafe<Registry>(REGISTRY_PATH);
  if (existing?.version === 1 && Array.isArray(existing.projects)) {
    return existing;
  }

  // Auto-discover and persist
  const projects = await discoverProjects();
  const registry: Registry = { version: 1, projects };
  await writeRegistry(registry);
  return registry;
}

export async function writeRegistry(registry: Registry): Promise<void> {
  await fs.mkdir(DRIFT_DIR, { recursive: true });
  await fs.writeFile(REGISTRY_PATH, JSON.stringify(registry, null, 2) + "\n");
}

// ── Staleness ──────────────────────────────────────────────────────────

const DAY_MS = 24 * 60 * 60 * 1000;

export function computeStaleness(
  manifestGenerated: string | null | undefined,
): Staleness {
  if (!manifestGenerated) return "no-manifest";

  const manifestDate = new Date(manifestGenerated).getTime();
  const age = Date.now() - manifestDate;

  if (age > 30 * DAY_MS) return "outdated";
  if (age > 7 * DAY_MS) return "stale";
  return "fresh";
}

// ── Plan Progress ──────────────────────────────────────────────────────

interface PlanItem {
  phase?: string;
}

interface AttackPlan {
  plan?: PlanItem[];
}

export function computePlanProgress(attackPlan: AttackPlan | null): PlanProgress {
  if (!attackPlan?.plan || !Array.isArray(attackPlan.plan)) {
    return { completed: 0, in_progress: 0, pending: 0, total: 0 };
  }

  let completed = 0;
  let in_progress = 0;
  let pending = 0;

  for (const item of attackPlan.plan) {
    const phase = item.phase ?? "planned";
    if (phase === "completed") completed++;
    else if (phase === "in_progress") in_progress++;
    else pending++;
  }

  return {
    completed,
    in_progress,
    pending,
    total: attackPlan.plan.length,
  };
}
