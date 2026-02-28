import path from "node:path";
import { Router } from "express";
import {
  readRegistry,
  readJsonSafe,
  computeStaleness,
  computePlanProgress,
} from "../registry.js";
import type { PlanProgress, Staleness } from "../registry.js";

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
      name: manifest?.project_name ?? project.name,
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
    name: manifest?.project_name ?? project.name,
    path: project.path,
    lastRun: manifest?.generated ?? project.lastRun,
    staleness: computeStaleness(manifest?.generated ?? project.lastRun),
    manifest,
    attackPlan,
    config,
  });
});
