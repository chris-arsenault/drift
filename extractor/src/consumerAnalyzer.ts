import * as path from "node:path";
import type { CodeUnit } from "./types.js";

/**
 * Build the consumer graph across all extracted units (second pass).
 *
 * For each unit, looks at its imports. For each internal import that resolves
 * to a file with known exported units, adds this unit as a consumer of those
 * target units. Then computes consumer counts, kinds, directories, and
 * co-occurrence data.
 *
 * Mutates units in place.
 */
/**
 * Link consumers by resolving internal imports to target units.
 * For each unit's internal import, adds the importing unit as a consumer
 * of the resolved target unit.
 */
// eslint-disable-next-line sonarjs/cognitive-complexity -- resolves imports across specifier patterns and file candidates
function linkConsumers(
  units: CodeUnit[],
  unitById: Map<string, CodeUnit>,
  unitsByFile: Map<string, string[]>
): void {
  for (const unit of units) {
    for (const imp of unit.imports) {
      if (imp.category !== "internal") continue;

      const resolvedTargets = resolveImportToFile(unit.filePath, imp.source, unitsByFile);

      for (const targetUnitId of resolvedTargets) {
        const targetUnit = unitById.get(targetUnitId);
        if (!targetUnit || targetUnit.id === unit.id) continue;

        const targetName = targetUnit.name;
        const specifierMatch =
          imp.specifiers.length === 0 ||
          imp.specifiers.some((spec) => {
            const baseName = spec.includes(" as ") ? spec.split(" as ")[0].trim() : spec;
            return baseName === targetName || baseName === "default" || spec.startsWith("* as");
          });

        if (specifierMatch && !targetUnit.consumers.includes(unit.id)) {
          targetUnit.consumers.push(unit.id);
        }
      }
    }
  }
}

/**
 * Compute consumer metadata: count, kinds, and directory spread.
 */
function computeConsumerMetadata(units: CodeUnit[], unitById: Map<string, CodeUnit>): void {
  for (const unit of units) {
    unit.consumerCount = unit.consumers.length;

    const kindSet = new Set<string>();
    const dirSet = new Set<string>();

    for (const consumerId of unit.consumers) {
      const consumer = unitById.get(consumerId);
      if (!consumer) continue;

      kindSet.add(consumer.kind);

      const parts = consumer.filePath.split("/");
      if (parts.length >= 2) {
        dirSet.add(parts.slice(0, 2).join("/"));
      } else {
        dirSet.add(parts[0]);
      }
    }

    unit.consumerKinds = [...kindSet].sort();
    unit.consumerDirectories = [...dirSet].sort();
  }
}

export function buildConsumerGraph(units: CodeUnit[]): void {
  const unitById = new Map<string, CodeUnit>();
  const unitsByFile = new Map<string, string[]>();

  for (const unit of units) {
    unitById.set(unit.id, unit);
    if (!unitsByFile.has(unit.filePath)) {
      unitsByFile.set(unit.filePath, []);
    }
    unitsByFile.get(unit.filePath)!.push(unit.id);
  }

  linkConsumers(units, unitById, unitsByFile);
  computeConsumerMetadata(units, unitById);
  buildCoOccurrences(units, unitById, unitsByFile);
}

/**
 * Resolve an import source path to file paths that may contain exported units.
 * Returns a list of unit IDs from the target file(s).
 */
function resolveImportToFile(
  importerFilePath: string,
  importSource: string,
  unitsByFile: Map<string, string[]>
): string[] {
  const importerDir = path.dirname(importerFilePath);
  let resolvedBase: string;

  if (importSource.startsWith(".")) {
    // Relative import
    resolvedBase = path.normalize(path.join(importerDir, importSource));
  } else if (importSource.startsWith("@/") || importSource.startsWith("~/")) {
    // Alias import -- best effort: strip prefix and try from root
    resolvedBase = importSource.slice(2);
  } else {
    // External package -- skip
    return [];
  }

  // Try various file extensions and index files
  const candidates = [
    resolvedBase,
    resolvedBase + ".ts",
    resolvedBase + ".tsx",
    resolvedBase + ".js",
    resolvedBase + ".jsx",
    resolvedBase + "/index.ts",
    resolvedBase + "/index.tsx",
    resolvedBase + "/index.js",
    resolvedBase + "/index.jsx",
  ];

  for (const candidate of candidates) {
    // Normalize path separators
    const normalized = candidate.replace(/\\/g, "/");
    const unitIds = unitsByFile.get(normalized);
    if (unitIds && unitIds.length > 0) {
      return unitIds;
    }
  }

  return [];
}

/**
 * Build co-occurrence data: for each file, gather the set of unit IDs imported
 * into that file. For each pair in that set, increment a co-occurrence counter.
 * Then for each unit, record the top co-occurring units.
 */
// eslint-disable-next-line sonarjs/cognitive-complexity -- multi-pass co-occurrence computation with nested pair counting
function buildCoOccurrences(
  units: CodeUnit[],
  unitById: Map<string, CodeUnit>,
  _unitsByFile: Map<string, string[]>
): void {
  // Map: unitId → set of files that import it (consumer files)
  const unitImportedBy = new Map<string, Set<string>>();
  for (const unit of units) {
    unitImportedBy.set(unit.id, new Set<string>());
  }

  // For each unit, its consumers are units that import it.
  // The consumer's file is the "importing file".
  for (const unit of units) {
    for (const consumerId of unit.consumers) {
      const consumer = unitById.get(consumerId);
      if (consumer) {
        unitImportedBy.get(unit.id)!.add(consumer.filePath);
      }
    }
  }

  // Build per-file import sets: filePath → set of unit IDs that file imports
  const fileImports = new Map<string, Set<string>>();
  for (const [unitId, importingFiles] of unitImportedBy) {
    for (const file of importingFiles) {
      if (!fileImports.has(file)) {
        fileImports.set(file, new Set());
      }
      fileImports.get(file)!.add(unitId);
    }
  }

  // Count co-occurrences: for each file's import set, count pairs
  const coOccurrenceCount = new Map<string, Map<string, number>>();

  for (const [, importedUnitIds] of fileImports) {
    const ids = [...importedUnitIds];
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        incrementCoOccurrence(coOccurrenceCount, ids[i], ids[j]);
        incrementCoOccurrence(coOccurrenceCount, ids[j], ids[i]);
      }
    }
  }

  // Assign top co-occurrences to each unit
  const MAX_CO_OCCURRENCES = 20;

  for (const unit of units) {
    const peerCounts = coOccurrenceCount.get(unit.id);
    if (!peerCounts || peerCounts.size === 0) continue;

    // Total files that import this unit
    const totalImportingFiles = unitImportedBy.get(unit.id)?.size ?? 1;

    // Sort by count descending and take top N
    const sorted = [...peerCounts.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, MAX_CO_OCCURRENCES);

    unit.coOccurrences = sorted.map(([peerId, count]) => ({
      unitId: peerId,
      count,
      ratio: totalImportingFiles > 0 ? count / totalImportingFiles : 0,
    }));
  }
}

function incrementCoOccurrence(map: Map<string, Map<string, number>>, a: string, b: string): void {
  if (!map.has(a)) map.set(a, new Map());
  const inner = map.get(a)!;
  inner.set(b, (inner.get(b) ?? 0) + 1);
}
