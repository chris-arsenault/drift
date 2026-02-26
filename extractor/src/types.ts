// ── Stage 1 EXTRACT output types ──────────────────────────────────────────

/** A single JSX element in the component tree structure */
export interface JsxTreeNode {
  tag: string;
  children: JsxTreeNode[];
  isMap: boolean;
  isConditional: boolean;
}

/** Parameter/prop extracted from a function or component signature */
export interface ParameterInfo {
  name: string;
  type: string;
  optional: boolean;
}

/** An import declaration with categorization */
export interface ImportEntry {
  source: string;
  specifiers: string[];
  category: "external" | "internal" | "framework";
}

/** A hook call with occurrence count */
export interface HookCallEntry {
  name: string;
  count: number;
}

/** A callee detected in the function body */
export interface CalleeEntry {
  target: string;
  context: "render" | "effect" | "handler" | "init" | "conditional";
}

/** A co-occurrence pair (units frequently imported together) */
export interface CoOccurrence {
  unitId: string;
  count: number;
  ratio: number;
}

/** Behavioral marker flags */
export interface BehaviorMarkers {
  isAsync: boolean;
  hasErrorHandling: boolean;
  hasLoadingState: boolean;
  hasEmptyState: boolean;
  hasRetryLogic: boolean;
  rendersIteration: boolean;
  rendersConditional: boolean;
  sideEffects: boolean;
}

/** JSX analysis results for component units */
export interface JsxInfo {
  jsxTree: JsxTreeNode;
  jsxLeafElements: string[];
  jsxDepth: number;
}

/** Hook usage analysis results */
export interface HookInfo {
  hookCalls: HookCallEntry[];
  customHookCalls: string[];
  stateVariableCount: number;
}

/** Import analysis results */
export interface ImportInfo {
  imports: ImportEntry[];
  storeAccess: string[];
  dataSourceAccess: string[];
}

/** Call graph analysis results */
export interface CallGraphInfo {
  callees: CalleeEntry[];
  calleeSequence: Record<string, string[]>;
  callDepth: number;
  uniqueCallees: number;
  chainPatterns: string[];
}

/**
 * A single extracted code unit -- the central data structure for Stage 1.
 *
 * id format: `relative/path.ts::ExportName`
 */
export interface CodeUnit {
  // ── Identity ────────────────────────────────────────────────────────────
  id: string;
  name: string;
  kind: "component" | "hook" | "function" | "class" | "type" | "constant" | "enum";
  filePath: string;
  lineRange: [number, number];
  sourceCode: string;

  // ── Type information ────────────────────────────────────────────────────
  parameters: ParameterInfo[];
  returnType: string;
  generics: string[];

  // ── JSX structure (components only, null for others) ────────────────────
  jsxTree: JsxTreeNode | null;
  jsxLeafElements: string[];
  jsxDepth: number;

  // ── Hooks & state ──────────────────────────────────────────────────────
  hookCalls: HookCallEntry[];
  customHookCalls: string[];
  stateVariableCount: number;

  // ── Dependencies (imports) ─────────────────────────────────────────────
  imports: ImportEntry[];
  storeAccess: string[];
  dataSourceAccess: string[];

  // ── Call graph (outbound) ──────────────────────────────────────────────
  callees: CalleeEntry[];
  calleeSequence: Record<string, string[]>;
  callDepth: number;
  uniqueCallees: number;
  chainPatterns: string[];

  // ── Consumer graph (inbound, filled in second pass) ────────────────────
  consumers: string[];
  consumerCount: number;
  consumerKinds: string[];
  consumerDirectories: string[];
  coOccurrences: CoOccurrence[];

  // ── Behavior markers ───────────────────────────────────────────────────
  isAsync: boolean;
  hasErrorHandling: boolean;
  hasLoadingState: boolean;
  hasEmptyState: boolean;
  hasRetryLogic: boolean;
  rendersIteration: boolean;
  rendersConditional: boolean;
  sideEffects: boolean;
}

/** Top-level extraction result written to code-units.json */
export interface ExtractionResult {
  metadata: {
    projectRoot: string;
    timestamp: string;
    unitCount: number;
    fileCount: number;
    extractionTimeMs: number;
  };
  units: CodeUnit[];
}
