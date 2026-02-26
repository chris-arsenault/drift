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

/** Glob for tsconfig files under apps/ and packages/, excluding noise. */
function findTsconfigFiles(projectRoot: string): string[] {
  const results: string[] = [];
  const searchDirs = ["apps", "packages"];

  for (const dir of searchDirs) {
    const base = path.join(projectRoot, dir);
    if (!fs.existsSync(base)) continue;
    walkForTsconfigs(base, results);
  }
  return results;
}

function walkForTsconfigs(dir: string, results: string[]): void {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    if (entry.name === "node_modules" || entry.name === "dist" || entry.name === ".turbo") continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walkForTsconfigs(full, results);
    } else if (entry.name === "tsconfig.json" || entry.name === "tsconfig.app.json") {
      results.push(full);
    }
  }
}

/**
 * Check whether a tsconfig's include patterns cover a given directory.
 * Returns true if any include glob, resolved relative to the tsconfig's dir,
 * would match files inside `targetDir`.
 */
function tsconfigCovers(tsconfigPath: string, targetDir: string): boolean {
  try {
    const raw = JSON.parse(fs.readFileSync(tsconfigPath, "utf-8"));
    const includes: string[] = raw.include ?? [];
    const tsconfigDir = path.dirname(tsconfigPath);

    for (const pattern of includes) {
      // Resolve the include pattern base relative to tsconfig dir
      const patternBase = pattern.replace(/\/\*.*$/, "").replace(/\*.*$/, "");
      const resolved = path.resolve(tsconfigDir, patternBase);
      // If the resolved base IS or is a parent of targetDir, it covers it
      const rel = path.relative(resolved, targetDir);
      if (!rel.startsWith("..") && !path.isAbsolute(rel)) {
        return true;
      }
    }
    return false;
  } catch {
    return false;
  }
}

/**
 * Find webui/src directories containing .jsx/.tsx files that are NOT covered
 * by any discovered tsconfig.
 */
function findUncoveredWebuis(projectRoot: string, tsconfigPaths: string[]): string[] {
  const uncovered: string[] = [];
  const searchDirs = ["apps", "packages"];

  for (const dir of searchDirs) {
    const base = path.join(projectRoot, dir);
    if (!fs.existsSync(base)) continue;

    const appDirs = fs.readdirSync(base, { withFileTypes: true });
    for (const appDir of appDirs) {
      if (!appDir.isDirectory()) continue;
      const webuiSrc = path.join(base, appDir.name, "webui", "src");
      if (!fs.existsSync(webuiSrc)) continue;

      // Check if any tsconfig covers this webui/src directory
      const covered = tsconfigPaths.some((tc) => tsconfigCovers(tc, webuiSrc));
      if (!covered) {
        uncovered.push(path.join(base, appDir.name, "webui"));
      }
    }
  }
  return uncovered;
}

/**
 * Load all TypeScript/JavaScript projects from the monorepo.
 *
 * - Creates a ts-morph Project for each tsconfig.json / tsconfig.app.json
 * - For webui directories not covered by any tsconfig, creates an ad-hoc Project
 *   with allowJs + JSX support
 * - Returns projects and a set of seen absolute file paths for deduplication
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

  // Find and create ad-hoc projects for uncovered webui directories
  const uncoveredWebuis = findUncoveredWebuis(projectRoot, selectedTsconfigs);

  for (const webuiDir of uncoveredWebuis) {
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

      // Add all .js/.jsx/.ts/.tsx files from the webui/src directory
      const srcDir = path.join(webuiDir, "src");
      if (fs.existsSync(srcDir)) {
        addSourceFilesRecursively(project, srcDir, seenFiles);
      }

      const sourceFiles = project.getSourceFiles();
      if (sourceFiles.length > 0) {
        projects.push(project);
        process.stderr.write(
          `  ad-hoc:   ${path.relative(projectRoot, webuiDir)}/src → ${sourceFiles.length} files\n`
        );
      }
    } catch (err) {
      process.stderr.write(
        `  WARN: failed to create ad-hoc project for ${path.relative(projectRoot, webuiDir)}: ${err}\n`
      );
    }
  }

  return { projects, seenFiles };
}

function addSourceFilesRecursively(project: Project, dir: string, seenFiles: Set<string>): void {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    if (entry.name === "node_modules" || entry.name === "dist") continue;
    const full = path.join(dir, entry.name);

    if (entry.isDirectory()) {
      addSourceFilesRecursively(project, full, seenFiles);
    } else if (/\.(ts|tsx|js|jsx)$/.test(entry.name) && !seenFiles.has(full)) {
      try {
        project.addSourceFileAtPath(full);
        seenFiles.add(full);
      } catch {
        // Skip files that fail to parse
      }
    }
  }
}
