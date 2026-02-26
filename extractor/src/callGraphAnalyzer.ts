import { Node, SyntaxKind, SourceFile } from "ts-morph";
import type { CallGraphInfo, CalleeEntry } from "./types.js";

type CallContext = CalleeEntry["context"];

/**
 * Analyze outbound call graph for a function/component/hook.
 *
 * Walks the function body, finds all CallExpression nodes, resolves targets,
 * classifies call context, and detects method chain patterns.
 */
export function analyzeCallGraph(node: Node, _sourceFile: SourceFile): CallGraphInfo {
  const callees: CalleeEntry[] = [];
  const calleesByContext = new Map<string, string[]>();
  const chainPatterns = new Set<string>();
  let maxChainDepth = 0;
  const uniqueTargets = new Set<string>();

  // Get the function body to analyze
  const body = getFunctionBody(node);
  if (!body) {
    return {
      callees: [],
      calleeSequence: {},
      callDepth: 0,
      uniqueCallees: 0,
      chainPatterns: [],
    };
  }

  // Find all call expressions
  body.forEachDescendant((desc) => {
    if (!Node.isCallExpression(desc)) return;

    // Skip if this call is inside a nested function definition (not our scope)
    // unless it's inside useEffect/useCallback/useMemo callbacks which ARE our scope
    if (isInsideNestedFunctionDef(desc, body)) return;

    const target = resolveCallTarget(desc);
    const context = classifyCallContext(desc, body);

    callees.push({ target, context });
    uniqueTargets.add(target);

    // Add to context-grouped sequence
    if (!calleesByContext.has(context)) {
      calleesByContext.set(context, []);
    }
    calleesByContext.get(context)!.push(target);

    // Detect method chain patterns
    const chainDepth = detectChainPattern(desc, chainPatterns);
    if (chainDepth > maxChainDepth) maxChainDepth = chainDepth;
  });

  // Build calleeSequence record
  const calleeSequence: Record<string, string[]> = {};
  for (const [ctx, targets] of calleesByContext) {
    calleeSequence[ctx] = targets;
  }

  return {
    callees,
    calleeSequence,
    callDepth: maxChainDepth,
    uniqueCallees: uniqueTargets.size,
    chainPatterns: [...chainPatterns],
  };
}

/**
 * Get the body node of a function-like declaration.
 */
function getFunctionBody(node: Node): Node | null {
  if (Node.isFunctionDeclaration(node) || Node.isMethodDeclaration(node)) {
    return node.getBody() ?? null;
  }
  if (Node.isVariableDeclaration(node)) {
    const init = node.getInitializer();
    if (init && (Node.isArrowFunction(init) || Node.isFunctionExpression(init))) {
      return init.getBody();
    }
    return null;
  }
  if (Node.isArrowFunction(node) || Node.isFunctionExpression(node)) {
    return node.getBody();
  }
  return null;
}

/**
 * Check if a node is inside a nested function definition (arrow, function expression)
 * that is NOT a hook callback (useEffect, useCallback, useMemo).
 */
function isInsideNestedFunctionDef(node: Node, outerBody: Node): boolean {
  let current = node.getParent();
  while (current && current !== outerBody) {
    if (
      Node.isArrowFunction(current) ||
      Node.isFunctionExpression(current) ||
      Node.isFunctionDeclaration(current)
    ) {
      // Check if this function is a callback to a hook or event handler
      const callParent = current.getParent();
      if (callParent && Node.isCallExpression(callParent)) {
        // This function IS the body -- it's a callback argument
        return false;
      }
      // Check if this is an argument to a call expression
      const grandParent = callParent?.getParent();
      if (grandParent && Node.isCallExpression(grandParent)) {
        return false;
      }
      // It's a standalone nested function definition
      return true;
    }
    current = current.getParent();
  }
  return false;
}

/**
 * Resolve the target of a call expression to a string identifier.
 */
function resolveCallTarget(callExpr: Node): string {
  if (!Node.isCallExpression(callExpr)) return "<unresolved>";

  const expr = callExpr.getExpression();

  // Simple identifier: foo()
  if (Node.isIdentifier(expr)) {
    return expr.getText();
  }

  // Property access: obj.method() or obj.prop.method()
  if (Node.isPropertyAccessExpression(expr)) {
    return resolvePropertyAccessChain(expr);
  }

  // Element access: obj['method']()
  if (Node.isElementAccessExpression(expr)) {
    const objText = expr.getExpression().getText();
    return `${objText}[...]`;
  }

  // Call expression result called: foo()()
  if (Node.isCallExpression(expr)) {
    const innerTarget = resolveCallTarget(expr);
    return `${innerTarget}()`;
  }

  return "<unresolved>";
}

/**
 * Resolve a property access chain: a.b.c → "a.b.c"
 * Limits depth to avoid pathologically long chains.
 */
function resolvePropertyAccessChain(expr: Node): string {
  if (!Node.isPropertyAccessExpression(expr)) {
    if (Node.isIdentifier(expr)) return expr.getText();
    if (Node.isCallExpression(expr)) return resolveCallTarget(expr) + "()";
    if (Node.isThisExpression(expr)) return "this";
    return "<expr>";
  }

  const obj = expr.getExpression();
  const prop = expr.getName();
  const objText = resolvePropertyAccessChain(obj);
  return `${objText}.${prop}`;
}

/**
 * Classify the context of a call expression within its containing function body.
 */
// eslint-disable-next-line sonarjs/cognitive-complexity -- walks AST parent chain classifying nested callback contexts
function classifyCallContext(callExpr: Node, outerBody: Node): CallContext {
  let current = callExpr.getParent();

  while (current && current !== outerBody) {
    // Inside useEffect callback → 'effect'
    if (
      isInsideHookCallback(current, "useEffect") ||
      isInsideHookCallback(current, "useLayoutEffect")
    ) {
      return "effect";
    }

    // Inside event handler (onXxx prop, onClick, onChange, etc.)
    if (isInsideEventHandler(current)) {
      return "handler";
    }

    // Inside conditional (if/ternary)
    if (
      current.getKind() === SyntaxKind.IfStatement ||
      current.getKind() === SyntaxKind.ConditionalExpression
    ) {
      return "conditional";
    }

    // Inside JSX expression (render context)
    if (current.getKind() === SyntaxKind.JsxExpression) {
      return "render";
    }

    // Inside return statement with JSX → render
    if (current.getKind() === SyntaxKind.ReturnStatement) {
      const expr = (current as unknown as { getExpression?: () => Node }).getExpression?.();
      if (expr && hasJsxDescendant(expr)) {
        return "render";
      }
    }

    current = current.getParent();
  }

  // Default: top-level in function body → init
  return "init";
}

function isInsideHookCallback(node: Node, hookName: string): boolean {
  const parent = node.getParent();
  if (!parent || !Node.isCallExpression(parent)) return false;

  const expr = parent.getExpression();
  if (Node.isIdentifier(expr) && expr.getText() === hookName) {
    // Check if `node` is the first argument (the callback)
    const args = parent.getArguments();
    return args.length > 0 && args[0] === node;
  }
  return false;
}

function isInsideEventHandler(node: Node): boolean {
  // Check if this node is a function assigned to a JSX attribute starting with "on"
  const parent = node.getParent();
  if (!parent) return false;

  if (Node.isJsxExpression(parent)) {
    const attrParent = parent.getParent();
    if (attrParent && Node.isJsxAttribute(attrParent)) {
      const attrName = attrParent.getNameNode().getText();
      if (/^on[A-Z]/.test(attrName)) return true;
    }
  }

  // Also check if this is an arrow function/function expression in a variable
  // whose name starts with "handle" or "on"
  if (Node.isVariableDeclaration(parent)) {
    const name = parent.getName();
    if (/^(handle[A-Z]|on[A-Z])/.test(name)) return true;
  }

  return false;
}

function hasJsxDescendant(node: Node): boolean {
  const kind = node.getKind();
  if (
    kind === SyntaxKind.JsxElement ||
    kind === SyntaxKind.JsxSelfClosingElement ||
    kind === SyntaxKind.JsxFragment
  ) {
    return true;
  }
  for (const child of node.getChildren()) {
    if (hasJsxDescendant(child)) return true;
  }
  return false;
}

/**
 * Detect method chain patterns and add wildcarded versions to the set.
 * Returns the chain depth.
 *
 * Example: db.entities.where('kind').equals('person').toArray()
 * → "db.*.where().equals().toArray()"
 */
function detectChainPattern(callExpr: Node, patterns: Set<string>): number {
  if (!Node.isCallExpression(callExpr)) return 0;

  const chain: string[] = [];
  let depth = 0;
  let current: Node = callExpr;

  // Walk up the chain of property accesses and calls
  while (Node.isCallExpression(current)) {
    const expr = (current as unknown as { getExpression: () => Node }).getExpression();
    if (!expr || !Node.isPropertyAccessExpression(expr)) break;

    const methodName = expr.getName();
    chain.unshift(methodName + "()");
    depth++;

    current = expr.getExpression();
  }

  // If chain has at least 3 segments, record it as a pattern
  if (chain.length >= 3) {
    // Get the root object
    let root = "<expr>";
    if (Node.isIdentifier(current)) {
      root = current.getText();
    } else if (Node.isPropertyAccessExpression(current)) {
      root = resolvePropertyAccessChain(current);
    }

    // Wildcard middle identifiers between root and the method chain
    const pattern = `${root}.*.${chain.join(".")}`;
    patterns.add(pattern);
  }

  return depth;
}
