import { Node, SyntaxKind } from "ts-morph";
import type { JsxInfo, JsxTreeNode } from "./types.js";

/**
 * Analyze JSX structure in a component function.
 *
 * Returns null for non-component functions (no JSX return).
 * Builds a nested tree of JSX elements with map/conditional markers.
 * Strips attributes/props -- we only care about structural nesting.
 */
export function analyzeJsx(node: Node): JsxInfo | null {
  // Find return statements that contain JSX
  const returnStatements = node.getDescendantsOfKind(SyntaxKind.ReturnStatement);

  let jsxRoot: Node | null = null;

  for (const ret of returnStatements) {
    const expr = ret.getExpression();
    if (!expr) continue;

    // Check if the return expression is JSX or a parenthesized JSX
    if (isJsxNode(expr)) {
      jsxRoot = expr;
      break;
    }

    // Check inside parenthesized expression
    if (Node.isParenthesizedExpression(expr)) {
      const inner = expr.getExpression();
      if (isJsxNode(inner)) {
        jsxRoot = inner;
        break;
      }
    }
  }

  // Also handle arrow functions with expression bodies (no explicit return):
  // const Foo = () => <div>...</div>
  if (!jsxRoot) {
    if (Node.isArrowFunction(node)) {
      const body = node.getBody();
      if (body && isJsxNode(body)) {
        jsxRoot = body;
      } else if (body && Node.isParenthesizedExpression(body)) {
        const inner = body.getExpression();
        if (isJsxNode(inner)) {
          jsxRoot = inner;
        }
      }
    }
    // For VariableDeclaration wrapping an arrow function
    if (!jsxRoot && Node.isVariableDeclaration(node)) {
      const init = node.getInitializer();
      if (init && Node.isArrowFunction(init)) {
        const body = init.getBody();
        if (body && isJsxNode(body)) {
          jsxRoot = body;
        } else if (body && Node.isParenthesizedExpression(body)) {
          const inner = body.getExpression();
          if (isJsxNode(inner)) {
            jsxRoot = inner;
          }
        }
      }
    }
  }

  if (!jsxRoot) return null;

  const tree = buildJsxTree(jsxRoot, false, false);
  if (!tree) return null;

  const leafElements: string[] = [];
  const depth = computeDepthAndLeaves(tree, leafElements);

  return {
    jsxTree: tree,
    jsxLeafElements: [...new Set(leafElements)],
    jsxDepth: depth,
  };
}

function isJsxNode(node: Node): boolean {
  const kind = node.getKind();
  return (
    kind === SyntaxKind.JsxElement ||
    kind === SyntaxKind.JsxSelfClosingElement ||
    kind === SyntaxKind.JsxFragment
  );
}

function getTagName(node: Node): string {
  if (Node.isJsxElement(node)) {
    return node.getOpeningElement().getTagNameNode().getText();
  }
  if (Node.isJsxSelfClosingElement(node)) {
    return node.getTagNameNode().getText();
  }
  if (Node.isJsxFragment(node)) {
    return "<>";
  }
  return "<unknown>";
}

function buildJsxTree(node: Node, isMap: boolean, isConditional: boolean): JsxTreeNode | null {
  if (Node.isJsxElement(node)) {
    const tag = getTagName(node);
    const children = processJsxChildren(node.getJsxChildren());
    return { tag, children, isMap, isConditional };
  }

  if (Node.isJsxSelfClosingElement(node)) {
    const tag = getTagName(node);
    return { tag, children: [], isMap, isConditional };
  }

  if (Node.isJsxFragment(node)) {
    const children = processJsxChildren(node.getJsxChildren());
    return { tag: "<>", children, isMap, isConditional };
  }

  return null;
}

function processJsxChildren(children: Node[]): JsxTreeNode[] {
  const result: JsxTreeNode[] = [];

  for (const child of children) {
    const kind = child.getKind();

    // Direct JSX elements
    if (isJsxNode(child)) {
      const tree = buildJsxTree(child, false, false);
      if (tree) result.push(tree);
      continue;
    }

    // JSX expression containers: { expression }
    if (kind === SyntaxKind.JsxExpression) {
      const trees = processJsxExpression(child);
      result.push(...trees);
      continue;
    }

    // JsxText with only whitespace is noise -- skip
    if (kind === SyntaxKind.JsxText) {
      continue;
    }
  }

  return result;
}

/**
 * Process a JSX expression container ({ ... }).
 * Detects .map() calls and conditional patterns.
 */
function processJsxExpression(node: Node): JsxTreeNode[] {
  const results: JsxTreeNode[] = [];

  // Get the expression inside the curly braces
  const children = node.getChildren();
  // JsxExpression has: OpenBraceToken, Expression, CloseBraceToken
  const expr = children.length >= 2 ? children[1] : null;
  if (!expr) return results;

  // .map() call producing JSX
  if (Node.isCallExpression(expr)) {
    const callExpr = expr.getExpression();
    if (Node.isPropertyAccessExpression(callExpr) && callExpr.getName() === "map") {
      const args = expr.getArguments();
      if (args.length > 0) {
        const callback = args[0];
        const jsxInCallback = findJsxInBody(callback);
        for (const jsx of jsxInCallback) {
          const tree = buildJsxTree(jsx, true, false);
          if (tree) results.push(tree);
        }
      }
      return results;
    }
  }

  // Conditional: condition && <Jsx>
  if (Node.isBinaryExpression(expr)) {
    const opKind = expr.getOperatorToken().getKind();
    if (opKind === SyntaxKind.AmpersandAmpersandToken) {
      const right = expr.getRight();
      if (isJsxNode(right)) {
        const tree = buildJsxTree(right, false, true);
        if (tree) results.push(tree);
      } else {
        // The right side might be a parenthesized JSX
        const jsxNodes = findJsxInNode(right);
        for (const jsx of jsxNodes) {
          const tree = buildJsxTree(jsx, false, true);
          if (tree) results.push(tree);
        }
      }
      return results;
    }
  }

  // Conditional: condition ? <A> : <B>
  if (Node.isConditionalExpression(expr)) {
    const whenTrue = expr.getWhenTrue();
    const whenFalse = expr.getWhenFalse();

    for (const branch of [whenTrue, whenFalse]) {
      if (isJsxNode(branch)) {
        const tree = buildJsxTree(branch, false, true);
        if (tree) results.push(tree);
      } else {
        const jsxNodes = findJsxInNode(branch);
        for (const jsx of jsxNodes) {
          const tree = buildJsxTree(jsx, false, true);
          if (tree) results.push(tree);
        }
      }
    }
    return results;
  }

  // Fallback: look for any JSX nodes inside the expression
  const jsxNodes = findJsxInNode(expr);
  for (const jsx of jsxNodes) {
    const tree = buildJsxTree(jsx, false, false);
    if (tree) results.push(tree);
  }

  return results;
}

/** Find JSX elements that are direct children or in simple wrappers in a callback body */
function findJsxInBody(node: Node): Node[] {
  const results: Node[] = [];

  // Arrow function with expression body: () => <div>
  if (Node.isArrowFunction(node)) {
    const body = node.getBody();
    if (isJsxNode(body)) {
      results.push(body);
      return results;
    }
    if (Node.isParenthesizedExpression(body)) {
      const inner = body.getExpression();
      if (isJsxNode(inner)) {
        results.push(inner);
        return results;
      }
    }
  }

  // Look for return statements containing JSX
  const returns = node.getDescendantsOfKind(SyntaxKind.ReturnStatement);
  for (const ret of returns) {
    const expr = ret.getExpression();
    if (expr && isJsxNode(expr)) {
      results.push(expr);
    } else if (expr && Node.isParenthesizedExpression(expr)) {
      const inner = expr.getExpression();
      if (isJsxNode(inner)) {
        results.push(inner);
      }
    }
  }

  // Also check for JSX directly at top level of the body
  if (results.length === 0) {
    for (const child of node.getChildren()) {
      if (isJsxNode(child)) {
        results.push(child);
      }
    }
  }

  return results;
}

/** Find immediate JSX nodes within a node (shallow search). */
function findJsxInNode(node: Node): Node[] {
  if (isJsxNode(node)) return [node];
  if (Node.isParenthesizedExpression(node)) {
    const inner = node.getExpression();
    if (isJsxNode(inner)) return [inner];
  }
  // Shallow search: only one level of children
  const results: Node[] = [];
  for (const child of node.getChildren()) {
    if (isJsxNode(child)) {
      results.push(child);
    }
  }
  return results;
}

/** Compute max depth and collect leaf element tag names. */
function computeDepthAndLeaves(tree: JsxTreeNode, leaves: string[]): number {
  if (tree.children.length === 0) {
    leaves.push(tree.tag);
    return 1;
  }

  let maxChildDepth = 0;
  for (const child of tree.children) {
    const d = computeDepthAndLeaves(child, leaves);
    if (d > maxChildDepth) maxChildDepth = d;
  }
  return 1 + maxChildDepth;
}
