import fs from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { Router } from "express";
import { readJsonSafe } from "../registry.js";

export const libraryRouter = Router();

// ── Types ──────────────────────────────────────────────────────────────

interface LibraryArtifact {
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

interface Library {
  version: number;
  artifacts: LibraryArtifact[];
}

// ── Paths ──────────────────────────────────────────────────────────────

const LIBRARY_DIR = path.join(os.homedir(), ".drift", "library");
const LIBRARY_PATH = path.join(LIBRARY_DIR, "library.json");

// ── GET / — Library index with stats ───────────────────────────────────

libraryRouter.get("/", async (_req, res) => {
  const library = await readJsonSafe<Library>(LIBRARY_PATH);

  if (!library) {
    res.json({ library: null, stats: { total: 0, byType: {} } });
    return;
  }

  const byType: Record<string, number> = {};
  for (const artifact of library.artifacts) {
    byType[artifact.type] = (byType[artifact.type] ?? 0) + 1;
  }

  res.json({
    library,
    stats: {
      total: library.artifacts.length,
      byType,
    },
  });
});

// ── GET /artifacts/:id — Single artifact with file content ─────────────

libraryRouter.get("/artifacts/:id", async (req, res) => {
  const library = await readJsonSafe<Library>(LIBRARY_PATH);

  if (!library) {
    res.status(404).json({ error: "Library not found" });
    return;
  }

  const artifact = library.artifacts.find((a) => a.id === req.params.id);
  if (!artifact) {
    res.status(404).json({ error: `Artifact "${req.params.id}" not found` });
    return;
  }

  let content: string | null = null;
  try {
    const filePath = path.join(LIBRARY_DIR, artifact.path);
    content = await fs.readFile(filePath, "utf-8");
  } catch {
    // File may not exist on disk
  }

  res.json({ artifact, content });
});
