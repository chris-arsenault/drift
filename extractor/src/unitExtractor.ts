import { SourceFile, Node, SyntaxKind } from "ts-morph";
import * as path from "node:path";
import type { CodeUnit, ParameterInfo, TypeMemberInfo } from "./types.js";
import { analyzeJsx } from "./jsxAnalyzer.js";
import { analyzeHooks } from "./hookAnalyzer.js";
import { analyzeImports } from "./importAnalyzer.js";
import { analyzeCallGraph } from "./callGraphAnalyzer.js";
import { analyzeBehavior } from "./behaviorMarkers.js";

const MAX_SOURCE_LINES = 300;

/**
 * Extract all exported code units from a source file.
 *
 * Iterates over all exported declarations, determines their kind,
 * runs all analyzers, and returns an array of CodeUnit records.
 */
export function extractUnits(sourceFile: SourceFile, projectRoot: string): CodeUnit[] {
  const units: CodeUnit[] = [];
  const relativePath = path.relative(projectRoot, sourceFile.getFilePath());

  // Import analysis is per-file (shared across all units in the file)
  const importInfo = analyzeImports(sourceFile, projectRoot);

  let exportedDeclarations: ReadonlyMap<string, Node[]>;
  try {
    exportedDeclarations = sourceFile.getExportedDeclarations();
  } catch {
    process.stderr.write(`  WARN: failed to get exports from ${relativePath}\n`);
    return units;
  }

  if (exportedDeclarations.size === 0) return units;

  for (const [exportName, declarations] of exportedDeclarations) {
    for (const decl of declarations) {
      try {
        const unit = extractSingleUnit(
          decl,
          exportName,
          relativePath,
          sourceFile,
          projectRoot,
          importInfo
        );
        if (unit) units.push(unit);
      } catch (err) {
        process.stderr.write(
          `  WARN: failed to extract ${exportName} from ${relativePath}: ${err}\n`
        );
      }
    }
  }

  const exportedNames = new Set(exportedDeclarations.keys());
  const nonExported = extractNonExportedUnits(
    sourceFile,
    projectRoot,
    exportedNames,
    importInfo
  );
  units.push(...nonExported);

  return units;
}

const MIN_NON_EXPORTED_LINES = 5;

/**
 * Collect non-exported function and variable declarations that have function
 * initializers. Returns raw candidates — caller applies naming/size filters.
 */
function collectNonExportedCandidates(sourceFile: SourceFile): { name: string; decl: Node }[] {
  const candidates: { name: string; decl: Node }[] = [];

  for (const fn of sourceFile.getDescendantsOfKind(SyntaxKind.FunctionDeclaration)) {
    const name = fn.getName();
    if (name && !fn.isExported()) {
      candidates.push({ name, decl: fn });
    }
  }

  for (const vd of sourceFile.getDescendantsOfKind(SyntaxKind.VariableDeclaration)) {
    const name = vd.getName();
    const init = vd.getInitializer();
    if (!name || !init) continue;
    if (!Node.isArrowFunction(init) && !Node.isFunctionExpression(init)) continue;
    const varStmt = vd.getFirstAncestorByKind(SyntaxKind.VariableStatement);
    if (varStmt && varStmt.isExported()) continue;
    candidates.push({ name, decl: vd });
  }

  return candidates;
}

/**
 * Extract non-exported hooks and components from a source file.
 *
 * Uses naming conventions (use[A-Z] for hooks, PascalCase+JSX for components)
 * and a minimum size filter. Skips names already in the exported set.
 */
function extractNonExportedUnits(
  sourceFile: SourceFile,
  projectRoot: string,
  exportedNames: Set<string>,
  importInfo: ReturnType<typeof analyzeImports>
): CodeUnit[] {
  const units: CodeUnit[] = [];
  const relativePath = path.relative(projectRoot, sourceFile.getFilePath());
  const seenNames = new Set<string>();
  const candidates = collectNonExportedCandidates(sourceFile);

  for (const { name, decl } of candidates) {
    if (exportedNames.has(name) || seenNames.has(name)) continue;

    const lines = decl.getEndLineNumber() - decl.getStartLineNumber() + 1;
    if (lines < MIN_NON_EXPORTED_LINES) continue;

    const kind = determineKind(decl, name);
    if (kind !== "hook" && kind !== "component") continue;

    seenNames.add(name);

    try {
      const unit = extractSingleUnit(decl, name, relativePath, sourceFile, projectRoot, importInfo);
      if (unit) units.push(unit);
    } catch (err) {
      process.stderr.write(
        `  WARN: failed to extract non-exported ${name} from ${relativePath}: ${err}\n`
      );
    }
  }

  return units;
}

// eslint-disable-next-line sonarjs/cognitive-complexity -- extracts metadata from many AST declaration types
function extractSingleUnit(
  decl: Node,
  exportName: string,
  relativePath: string,
  sourceFile: SourceFile,
  projectRoot: string,
  importInfo: ReturnType<typeof analyzeImports>
): CodeUnit | null {
  const kind = determineKind(decl, exportName);
  if (!kind) return null;

  const id = `${relativePath}::${exportName}`;

  // Source code extraction
  const sourceCode = extractSourceCode(decl);

  // Line range
  const startLine = decl.getStartLineNumber();
  const endLine = decl.getEndLineNumber();
  const lineRange: [number, number] = [startLine, endLine];

  // Type information
  const parameters = extractParameters(decl);
  const returnType = extractReturnType(decl);
  const generics = extractGenerics(decl);
  const typeMembers = extractTypeMembers(decl);

  // Get the function-like node for body analysis (may be the decl itself or its initializer)
  const analyzableNode = getAnalyzableNode(decl);

  // JSX analysis (components only)
  let jsxInfo = null;
  if (kind === "component" && analyzableNode) {
    try {
      jsxInfo = analyzeJsx(analyzableNode);
    } catch {
      // JSX analysis failed -- non-critical
    }
  }

  // Hook analysis
  let hookInfo = { hookCalls: [], customHookCalls: [], stateVariableCount: 0 } as ReturnType<
    typeof analyzeHooks
  >;
  if ((kind === "component" || kind === "hook") && analyzableNode) {
    try {
      hookInfo = analyzeHooks(analyzableNode);
    } catch {
      // Hook analysis failed -- non-critical
    }
  }

  // Call graph analysis
  let callGraphInfo = {
    callees: [],
    calleeSequence: {},
    callDepth: 0,
    uniqueCallees: 0,
    chainPatterns: [],
  } as ReturnType<typeof analyzeCallGraph>;
  if ((kind === "component" || kind === "hook" || kind === "function") && analyzableNode) {
    try {
      callGraphInfo = analyzeCallGraph(analyzableNode, sourceFile);
    } catch {
      // Call graph analysis failed -- non-critical
    }
  }

  // Behavior markers
  let behavior = {
    isAsync: false,
    hasErrorHandling: false,
    hasLoadingState: false,
    hasEmptyState: false,
    hasRetryLogic: false,
    rendersIteration: false,
    rendersConditional: false,
    sideEffects: false,
  };
  if (analyzableNode) {
    try {
      behavior = analyzeBehavior(analyzableNode);
    } catch {
      // Behavior analysis failed -- non-critical
    }
  }

  return {
    // Identity
    id,
    name: exportName,
    kind,
    filePath: relativePath,
    lineRange,
    sourceCode,

    // Type information
    parameters,
    returnType,
    generics,
    typeMembers,

    // JSX
    jsxTree: jsxInfo?.jsxTree ?? null,
    jsxLeafElements: jsxInfo?.jsxLeafElements ?? [],
    jsxDepth: jsxInfo?.jsxDepth ?? 0,

    // Hooks
    hookCalls: hookInfo.hookCalls,
    customHookCalls: hookInfo.customHookCalls,
    stateVariableCount: hookInfo.stateVariableCount,

    // Imports (shared per-file)
    imports: importInfo.imports,
    storeAccess: importInfo.storeAccess,
    dataSourceAccess: importInfo.dataSourceAccess,

    // Call graph
    callees: callGraphInfo.callees,
    calleeSequence: callGraphInfo.calleeSequence,
    callDepth: callGraphInfo.callDepth,
    uniqueCallees: callGraphInfo.uniqueCallees,
    chainPatterns: callGraphInfo.chainPatterns,

    // Consumer graph (filled in second pass)
    consumers: [],
    consumerCount: 0,
    consumerKinds: [],
    consumerDirectories: [],
    coOccurrences: [],

    // Behavior
    isAsync: behavior.isAsync,
    hasErrorHandling: behavior.hasErrorHandling,
    hasLoadingState: behavior.hasLoadingState,
    hasEmptyState: behavior.hasEmptyState,
    hasRetryLogic: behavior.hasRetryLogic,
    rendersIteration: behavior.rendersIteration,
    rendersConditional: behavior.rendersConditional,
    sideEffects: behavior.sideEffects,
  };
}

/**
 * Determine the kind of a declaration.
 * Returns null for declarations we don't extract (e.g. re-exports of externals).
 */
function determineKind(decl: Node, exportName: string): CodeUnit["kind"] | null {
  // Interface
  if (Node.isInterfaceDeclaration(decl)) return "type";

  // Type alias
  if (Node.isTypeAliasDeclaration(decl)) return "type";

  // Enum
  if (Node.isEnumDeclaration(decl)) return "enum";

  // Class
  if (Node.isClassDeclaration(decl)) return "class";

  // Function declaration
  if (Node.isFunctionDeclaration(decl)) {
    return classifyFunction(exportName, decl);
  }

  // Variable declaration (const Foo = () => ... or const FOO = ...)
  if (Node.isVariableDeclaration(decl)) {
    const init = decl.getInitializer();
    if (init && (Node.isArrowFunction(init) || Node.isFunctionExpression(init))) {
      return classifyFunction(exportName, init);
    }
    // Non-function constant
    return "constant";
  }

  // Expression (e.g., `export default someExpression`)
  // Skip these -- they're usually re-exports or complex expressions
  return null;
}

/**
 * Classify a function as component, hook, or plain function.
 */
function classifyFunction(name: string, node: Node): "component" | "hook" | "function" {
  // Hook: starts with "use" followed by uppercase letter
  if (/^use[A-Z]/.test(name)) return "hook";

  // Component: PascalCase name and either:
  //   - returns JSX (check for JSX in return/body)
  //   - OR name is PascalCase (heuristic for components without JSX in this analysis pass)
  if (/^[A-Z]/.test(name)) {
    // Check if the function body contains JSX
    if (containsJsx(node)) return "component";

    // PascalCase functions that might be components (React.memo, forwardRef wrappers etc.)
    // In ambiguous cases, PascalCase + no JSX = still treat as component if it has typical patterns
    // But to be safe, fall through to function for non-JSX PascalCase functions
  }

  return "function";
}

/**
 * Check if a node or its body contains JSX elements.
 */
function containsJsx(node: Node): boolean {
  try {
    const descendants = node.getDescendants();
    for (const d of descendants) {
      const kind = d.getKind();
      if (
        kind === SyntaxKind.JsxElement ||
        kind === SyntaxKind.JsxSelfClosingElement ||
        kind === SyntaxKind.JsxFragment
      ) {
        return true;
      }
    }
  } catch {
    // Failed to traverse -- not critical
  }
  return false;
}

/**
 * Get the node that should be analyzed for hooks, calls, behavior, JSX.
 * For variable declarations wrapping arrow functions, return the arrow function.
 * For function declarations, return the declaration itself.
 */
function getAnalyzableNode(decl: Node): Node | null {
  if (Node.isFunctionDeclaration(decl) || Node.isMethodDeclaration(decl)) {
    return decl;
  }
  if (Node.isVariableDeclaration(decl)) {
    const init = decl.getInitializer();
    if (init && (Node.isArrowFunction(init) || Node.isFunctionExpression(init))) {
      return init;
    }
    return decl;
  }
  if (Node.isClassDeclaration(decl)) {
    return decl;
  }
  return null;
}

/**
 * Extract the source code text of a declaration, capped at MAX_SOURCE_LINES.
 */
function extractSourceCode(decl: Node): string {
  try {
    const text = decl.getFullText().trim();
    const lines = text.split("\n");
    if (lines.length > MAX_SOURCE_LINES) {
      return lines.slice(0, MAX_SOURCE_LINES).join("\n") + "\n// ... (truncated)";
    }
    return text;
  } catch {
    return "";
  }
}

/**
 * Extract parameter information from a function-like declaration.
 */
function extractParameters(decl: Node): ParameterInfo[] {
  const params: ParameterInfo[] = [];

  let paramNodes: Node[] = [];

  if (Node.isFunctionDeclaration(decl) || Node.isMethodDeclaration(decl)) {
    paramNodes = decl.getParameters();
  } else if (Node.isVariableDeclaration(decl)) {
    const init = decl.getInitializer();
    if (init && (Node.isArrowFunction(init) || Node.isFunctionExpression(init))) {
      paramNodes = init.getParameters();
    }
  }

  for (const p of paramNodes) {
    if (!Node.isParameterDeclaration(p)) continue;

    const name = p.getName();
    let type = "unknown";
    try {
      const typeNode = p.getTypeNode();
      if (typeNode) {
        type = typeNode.getText();
      } else {
        // Try to get inferred type
        type = p.getType().getText(p);
      }
    } catch {
      type = "unknown";
    }

    // Cap excessively long types
    if (type.length > 500) {
      type = type.slice(0, 497) + "...";
    }

    const optional = p.hasQuestionToken() || p.hasInitializer();

    params.push({ name, type, optional });
  }

  return params;
}

/**
 * Extract the return type string from a function-like declaration.
 */
function extractReturnType(decl: Node): string {
  try {
    if (Node.isFunctionDeclaration(decl) || Node.isMethodDeclaration(decl)) {
      const rtNode = decl.getReturnTypeNode();
      if (rtNode) return rtNode.getText();
      return decl.getReturnType().getText(decl);
    }

    if (Node.isVariableDeclaration(decl)) {
      const init = decl.getInitializer();
      if (init && (Node.isArrowFunction(init) || Node.isFunctionExpression(init))) {
        const rtNode = init.getReturnTypeNode();
        if (rtNode) return rtNode.getText();
        return init.getReturnType().getText(init);
      }
    }
  } catch {
    // Type resolution failed
  }
  return "unknown";
}

/**
 * Extract generic type parameter names.
 */
function extractGenerics(decl: Node): string[] {
  try {
    let typeParams: Node[] = [];

    if (
      Node.isFunctionDeclaration(decl) ||
      Node.isClassDeclaration(decl) ||
      Node.isInterfaceDeclaration(decl) ||
      Node.isTypeAliasDeclaration(decl)
    ) {
      typeParams = decl.getTypeParameters?.() ?? [];
    } else if (Node.isVariableDeclaration(decl)) {
      const init = decl.getInitializer();
      if (init && (Node.isArrowFunction(init) || Node.isFunctionExpression(init))) {
        typeParams = init.getTypeParameters?.() ?? [];
      }
    }

    return typeParams.map((tp) => {
      if (Node.isTypeParameterDeclaration(tp)) {
        return tp.getName();
      }
      return tp.getText();
    });
  } catch {
    return [];
  }
}

/**
 * Extract member properties from interface or type alias declarations.
 * Only extracts top-level property signatures (not methods, index signatures, etc.).
 */
function extractTypeMembers(decl: Node): TypeMemberInfo[] {
  const members: TypeMemberInfo[] = [];

  let memberNodes: Node[] = [];

  if (Node.isInterfaceDeclaration(decl)) {
    memberNodes = decl.getMembers();
  } else if (Node.isTypeAliasDeclaration(decl)) {
    const typeNode = decl.getTypeNode();
    if (typeNode && Node.isTypeLiteral(typeNode)) {
      memberNodes = typeNode.getMembers();
    }
  }

  for (const m of memberNodes) {
    if (!Node.isPropertySignature(m)) continue;
    const name = m.getName();
    let type = "unknown";
    try {
      const typeNode = m.getTypeNode();
      if (typeNode) {
        type = typeNode.getText();
      } else {
        type = m.getType().getText(m);
      }
    } catch {
      type = "unknown";
    }
    if (type.length > 500) {
      type = type.slice(0, 497) + "...";
    }
    const optional = m.hasQuestionToken();
    members.push({ name, type, optional });
  }

  return members;
}
