import * as path from "node:path";
import * as fs from "node:fs";
import { loadProjects } from "./projectLoader.js";
import { extractUnits } from "./unitExtractor.js";
import { buildConsumerGraph } from "./consumerAnalyzer.js";
import type { CodeUnit, ExtractionResult } from "./types.js";

/**
 * Main entry point for Stage 1: EXTRACT.
 *
 * Usage:
 *   npx tsx src/extract.ts --project <path> [--output <path>]
 */
function main(): void {
  const args = process.argv.slice(2);
  const projectRoot = resolveArg(args, "--project");
  const outputPath =
    resolveArg(args, "--output") ?? path.join(".drift-audit", "semantic", "code-units.json");

  if (!projectRoot) {
    process.stderr.write("Usage: extract --project <path> [--output <path>]\n");
    process.exit(1);
  }

  const resolvedRoot = path.resolve(projectRoot);
  if (!fs.existsSync(resolvedRoot)) {
    process.stderr.write(`ERROR: project root does not exist: ${resolvedRoot}\n`);
    process.exit(1);
  }

  process.stderr.write(`Extracting code units from: ${resolvedRoot}\n`);
  const startTime = Date.now();

  // Load ts-morph projects
  process.stderr.write("Loading projects...\n");
  const { projects, seenFiles } = loadProjects(resolvedRoot);
  process.stderr.write(`  Loaded ${projects.length} projects covering ${seenFiles.size} files\n`);

  // Extract units from all source files
  process.stderr.write("Extracting units...\n");
  const allUnits: CodeUnit[] = [];
  const processedFiles = new Set<string>();
  let fileCount = 0;

  for (const project of projects) {
    const sourceFiles = project.getSourceFiles();

    for (const sourceFile of sourceFiles) {
      const absPath = sourceFile.getFilePath();

      // Deduplicate files across projects
      if (processedFiles.has(absPath)) continue;
      processedFiles.add(absPath);

      // Skip node_modules, dist, test files
      const relPath = path.relative(resolvedRoot, absPath);
      if (
        relPath.includes("node_modules") ||
        relPath.includes("/dist/") ||
        relPath.startsWith("dist/")
      )
        continue;
      if (relPath.includes("__tests__") || relPath.includes(".test.") || relPath.includes(".spec."))
        continue;

      try {
        const units = extractUnits(sourceFile, resolvedRoot);
        if (units.length > 0) {
          allUnits.push(...units);
          fileCount++;
        }
      } catch (err) {
        process.stderr.write(`  WARN: failed to process ${relPath}: ${err}\n`);
      }
    }
  }

  process.stderr.write(`  Extracted ${allUnits.length} units from ${fileCount} files\n`);

  // Second pass: build consumer graph
  process.stderr.write("Building consumer graph...\n");
  buildConsumerGraph(allUnits);

  const elapsed = Date.now() - startTime;

  // Build result
  const result: ExtractionResult = {
    metadata: {
      projectRoot: resolvedRoot,
      timestamp: new Date().toISOString(),
      unitCount: allUnits.length,
      fileCount,
      extractionTimeMs: elapsed,
    },
    units: allUnits,
  };

  // Write output
  const resolvedOutput = path.resolve(resolvedRoot, outputPath);
  const outputDir = path.dirname(resolvedOutput);
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }
  fs.writeFileSync(resolvedOutput, JSON.stringify(result, null, 2));

  // Summary to stderr
  const kindBreakdown = new Map<string, number>();
  for (const unit of allUnits) {
    kindBreakdown.set(unit.kind, (kindBreakdown.get(unit.kind) ?? 0) + 1);
  }

  process.stderr.write("\n── Extraction complete ──\n");
  process.stderr.write(`  Time:  ${elapsed}ms\n`);
  process.stderr.write(`  Files: ${fileCount}\n`);
  process.stderr.write(`  Units: ${allUnits.length}\n`);
  process.stderr.write("  Kinds:\n");
  for (const [kind, count] of [...kindBreakdown.entries()].sort((a, b) => b[1] - a[1])) {
    process.stderr.write(`    ${kind}: ${count}\n`);
  }
  process.stderr.write(`  Output: ${resolvedOutput}\n`);
}

function resolveArg(args: string[], flag: string): string | undefined {
  const idx = args.indexOf(flag);
  if (idx === -1 || idx + 1 >= args.length) return undefined;
  return args[idx + 1];
}

main();
