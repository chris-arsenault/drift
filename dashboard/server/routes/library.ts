import fs from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { Router } from "express";
import { readJsonSafe } from "../registry.js";

const execFileAsync = promisify(execFile);

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

// ── Git helpers ─────────────────────────────────────────────────────────

async function isGitRepo(): Promise<boolean> {
  try {
    await execFileAsync("git", ["-C", LIBRARY_DIR, "rev-parse", "--git-dir"]);
    return true;
  } catch {
    return false;
  }
}

async function git(...args: string[]): Promise<string> {
  const { stdout } = await execFileAsync("git", ["-C", LIBRARY_DIR, ...args]);
  return stdout.trim();
}

// ── GET /git-status ─────────────────────────────────────────────────────

libraryRouter.get("/git-status", async (_req, res) => {
  if (!(await isGitRepo())) {
    // Auto-init git if the library directory exists
    try {
      await fs.access(LIBRARY_DIR);
      await execFileAsync("git", ["-C", LIBRARY_DIR, "init", "-b", "main"]);
    } catch {
      res.json({
        isGitRepo: false,
        hasRemote: false,
        remoteUrl: null,
        branch: null,
        isDirty: false,
        commitCount: 0,
        ahead: 0,
        behind: 0,
      });
      return;
    }
  }

  let remoteUrl: string | null = null;
  try {
    remoteUrl = await git("remote", "get-url", "origin");
  } catch {
    // no remote
  }

  let branch: string | null = null;
  try {
    branch = await git("branch", "--show-current");
  } catch {
    // empty repo
  }

  let isDirty = false;
  try {
    const status = await git("status", "--porcelain");
    isDirty = status.length > 0;
  } catch {
    // empty repo
  }

  let commitCount = 0;
  try {
    const count = await git("rev-list", "--count", "HEAD");
    commitCount = parseInt(count, 10) || 0;
  } catch {
    // no commits
  }

  let ahead = 0;
  let behind = 0;
  if (remoteUrl && branch) {
    try {
      await git("fetch", "origin", "--quiet");
      const counts = await git(
        "rev-list",
        "--left-right",
        "--count",
        `origin/${branch}...HEAD`,
      );
      const [b, a] = counts.split(/\s+/).map(Number);
      behind = b || 0;
      ahead = a || 0;
    } catch {
      // remote branch may not exist yet
    }
  }

  res.json({
    isGitRepo: true,
    hasRemote: remoteUrl !== null,
    remoteUrl,
    branch,
    isDirty,
    commitCount,
    ahead,
    behind,
  });
});

// ── POST /git-commit ────────────────────────────────────────────────────

libraryRouter.post("/git-commit", async (_req, res) => {
  if (!(await isGitRepo())) {
    res.status(400).json({ error: "Library is not a git repository" });
    return;
  }

  try {
    await git("add", "-A");

    // Check if there's anything to commit
    try {
      await git("diff", "--cached", "--quiet");
      res.json({ message: "Nothing to commit — library is clean" });
      return;
    } catch {
      // non-zero exit = staged changes exist, proceed
    }

    const diffStat = await git("diff", "--cached", "--name-only");
    const count = diffStat.split("\n").filter(Boolean).length;
    const msg = `Update library: ${count} file(s) modified`;

    await git("commit", "-m", msg);
    res.json({ message: msg });
  } catch (err) {
    res.status(500).json({
      error: `Commit failed: ${(err as Error).message}`,
    });
  }
});

// ── POST /git-remote ────────────────────────────────────────────────────

libraryRouter.post("/git-remote", async (req, res) => {
  if (!(await isGitRepo())) {
    res.status(400).json({ error: "Library is not a git repository" });
    return;
  }

  const { url } = req.body as { url?: string };
  if (!url || typeof url !== "string") {
    res.status(400).json({ error: "Missing or invalid 'url' in request body" });
    return;
  }

  try {
    let hasOrigin = false;
    try {
      await git("remote", "get-url", "origin");
      hasOrigin = true;
    } catch {
      // no origin
    }

    if (hasOrigin) {
      await git("remote", "set-url", "origin", url);
    } else {
      await git("remote", "add", "origin", url);
    }

    res.json({ message: `Remote origin set to: ${url}` });
  } catch (err) {
    res.status(500).json({
      error: `Failed to set remote: ${(err as Error).message}`,
    });
  }
});

// ── POST /git-push ──────────────────────────────────────────────────────

libraryRouter.post("/git-push", async (_req, res) => {
  if (!(await isGitRepo())) {
    res.status(400).json({ error: "Library is not a git repository" });
    return;
  }

  try {
    const branch = await git("branch", "--show-current");
    await git("push", "-u", "origin", branch);
    res.json({ message: "Pushed to remote" });
  } catch (err) {
    res.status(500).json({
      error: `Push failed: ${(err as Error).message}`,
    });
  }
});

// ── POST /git-pull ──────────────────────────────────────────────────────

libraryRouter.post("/git-pull", async (_req, res) => {
  if (!(await isGitRepo())) {
    res.status(400).json({ error: "Library is not a git repository" });
    return;
  }

  try {
    await git("pull", "--ff-only");
    res.json({ message: "Pulled from remote" });
  } catch (err) {
    res.status(500).json({
      error: `Pull failed: ${(err as Error).message}`,
    });
  }
});
