import { Project, ts } from "ts-morph";
import * as path from "node:path";
import * as fs from "node:fs";

/**
 * Result of loading projects, including the deduplication set so callers
 * can skip files already processed by a previous Project.
 */
export interface LoadedProjects {
  projects: Project[];
  seenFiles: Set<string>;
}

/** Directories to skip when walking the project tree. */
const SKIP_DIRS = new Set([
  "node_modules",
  "dist",
  ".turbo",
  ".next",
  "build",
  "coverage",
  ".git",
  "__pycache__",
  ".venv",
  "venv",
  ".drift-audit",
]);

const SOURCE_EXTS = /\.(ts|tsx|js|jsx)$/;

/** Walk the project tree for tsconfig files, skipping noise directories. */
function findTsconfigFiles(projectRoot: string): string[] {
  const results: string[] = [];
  walkForTsconfigs(projectRoot, results);
  return results;
}

function walkForTsconfigs(dir: string, results: string[]): void {
  let entries: fs.Dirent[];
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return; // Permission denied, etc.
  }
  for (const entry of entries) {
    if (SKIP_DIRS.has(entry.name)) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walkForTsconfigs(full, results);
    } else if (entry.name === "tsconfig.json" || entry.name === "tsconfig.app.json") {
      results.push(full);
    }
  }
}

/**
 * Find directories containing source files not covered by any tsconfig.
 *
 * Walks the project tree looking for .ts/.tsx/.js/.jsx files. For each file
 * not in seenFiles, records its parent directory. Returns the minimal set of
 * root directories that contain uncovered source files.
 */
function findUncoveredSourceDirs(
  projectRoot: string,
  seenFiles: Set<string>,
): string[] {
  const uncoveredDirs = new Set<string>();
  walkForUncoveredSources(projectRoot, seenFiles, uncoveredDirs);

  // Reduce to root-level source dirs: if both /a and /a/b are collected,
  // keep only /a (it will be scanned recursively).
  const sorted = [...uncoveredDirs].sort();
  const roots: string[] = [];
  for (const dir of sorted) {
    const isNested = roots.some(
      (root) => dir.startsWith(root + path.sep) || dir === root,
    );
    if (!isNested) {
      roots.push(dir);
    }
  }
  return roots;
}

function walkForUncoveredSources(
  dir: string,
  seenFiles: Set<string>,
  uncoveredDirs: Set<string>,
): void {
  let entries: fs.Dirent[];
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    if (SKIP_DIRS.has(entry.name)) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walkForUncoveredSources(full, seenFiles, uncoveredDirs);
    } else if (SOURCE_EXTS.test(entry.name) && !seenFiles.has(full)) {
      uncoveredDirs.add(dir);
    }
  }
}

/**
 * Load all TypeScript/JavaScript projects from any directory structure.
 *
 * 1. Walks the entire project tree for tsconfig.json / tsconfig.app.json
 * 2. Creates a ts-morph Project for each (preferring tsconfig.app.json)
 * 3. For source directories not covered by any tsconfig, creates ad-hoc
 *    Projects with allowJs + JSX support
 * 4. Returns projects and a set of seen absolute file paths for deduplication
 */
export function loadProjects(projectRoot: string): LoadedProjects {
  const tsconfigPaths = findTsconfigFiles(projectRoot);
  const seenFiles = new Set<string>();
  const projects: Project[] = [];

  // Prefer tsconfig.app.json over tsconfig.json when both exist in same dir
  const byDir = new Map<string, string[]>();
  for (const tc of tsconfigPaths) {
    const dir = path.dirname(tc);
    if (!byDir.has(dir)) byDir.set(dir, []);
    byDir.get(dir)!.push(tc);
  }

  const selectedTsconfigs: string[] = [];
  for (const [, configs] of byDir) {
    const appConfig = configs.find((c) => path.basename(c) === "tsconfig.app.json");
    // If tsconfig.app.json exists, prefer it (it's the actual source config);
    // otherwise use tsconfig.json
    selectedTsconfigs.push(appConfig ?? configs[0]);
  }

  for (const tsconfigPath of selectedTsconfigs) {
    try {
      const project = new Project({ tsConfigFilePath: tsconfigPath });
      const sourceFiles = project.getSourceFiles();

      // Track which files this project covers
      for (const sf of sourceFiles) {
        seenFiles.add(sf.getFilePath());
      }

      projects.push(project);
      process.stderr.write(
        `  tsconfig: ${path.relative(projectRoot, tsconfigPath)} → ${sourceFiles.length} files\n`
      );
    } catch (err) {
      process.stderr.write(
        `  WARN: failed to load ${path.relative(projectRoot, tsconfigPath)}: ${err}\n`
      );
    }
  }

  // Find and create ad-hoc projects for directories with source files
  // not covered by any tsconfig
  const uncoveredDirs = findUncoveredSourceDirs(projectRoot, seenFiles);

  for (const srcDir of uncoveredDirs) {
    try {
      const project = new Project({
        compilerOptions: {
          target: ts.ScriptTarget.ES2022,
          module: ts.ModuleKind.ESNext,
          moduleResolution: ts.ModuleResolutionKind.Bundler,
          allowJs: true,
          jsx: ts.JsxEmit.ReactJSX,
          strict: false,
          noEmit: true,
          esModuleInterop: true,
          skipLibCheck: true,
        },
      });

      addSourceFilesRecursively(project, srcDir, seenFiles);

      const sourceFiles = project.getSourceFiles();
      if (sourceFiles.length > 0) {
        projects.push(project);
        process.stderr.write(
          `  ad-hoc:   ${path.relative(projectRoot, srcDir)} → ${sourceFiles.length} files\n`
        );
      }
    } catch (err) {
      process.stderr.write(
        `  WARN: failed to create ad-hoc project for ${path.relative(projectRoot, srcDir)}: ${err}\n`
      );
    }
  }

  return { projects, seenFiles };
}

function addSourceFilesRecursively(project: Project, dir: string, seenFiles: Set<string>): void {
  let entries: fs.Dirent[];
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    if (SKIP_DIRS.has(entry.name)) continue;
    const full = path.join(dir, entry.name);

    if (entry.isDirectory()) {
      addSourceFilesRecursively(project, full, seenFiles);
    } else if (SOURCE_EXTS.test(entry.name) && !seenFiles.has(full)) {
      try {
        project.addSourceFileAtPath(full);
        seenFiles.add(full);
      } catch {
        // Skip files that fail to parse
      }
    }
  }
}
