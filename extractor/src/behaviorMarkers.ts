import { Node, SyntaxKind } from "ts-morph";
import type { BehaviorMarkers } from "./types.js";

/**
 * Walk the AST subtree rooted at `node` and detect behavioral markers.
 */
export function analyzeBehavior(node: Node): BehaviorMarkers {
  const markers: BehaviorMarkers = {
    isAsync: false,
    hasErrorHandling: false,
    hasLoadingState: false,
    hasEmptyState: false,
    hasRetryLogic: false,
    rendersIteration: false,
    rendersConditional: false,
    sideEffects: false,
  };

  // Check if the function itself is async
  if (Node.isFunctionDeclaration(node) || Node.isMethodDeclaration(node)) {
    markers.isAsync = node.isAsync();
  } else if (Node.isVariableDeclaration(node)) {
    const init = node.getInitializer();
    if (init && Node.isArrowFunction(init)) {
      markers.isAsync = init.isAsync();
    } else if (init && Node.isFunctionExpression(init)) {
      markers.isAsync = init.isAsync();
    }
  }

  // Walk the full subtree once and check patterns
  node.forEachDescendant((desc) => {
    const kindNum = desc.getKind();

    // hasErrorHandling: try/catch or .catch()
    if (kindNum === SyntaxKind.TryStatement) {
      markers.hasErrorHandling = true;
    }
    if (Node.isPropertyAccessExpression(desc) && desc.getName() === "catch") {
      markers.hasErrorHandling = true;
    }

    // hasLoadingState: variable/state named loading/isLoading/pending
    if (Node.isIdentifier(desc)) {
      const name = desc.getText();
      if (/^(loading|isLoading|isPending|pending|isSubmitting)$/.test(name)) {
        markers.hasLoadingState = true;
      }
      // hasRetryLogic: retry/attempt/MAX_RETRIES identifiers
      if (/^(retry|retryCount|attempt|attempts|MAX_RETRIES|maxRetries|retries)$/i.test(name)) {
        markers.hasRetryLogic = true;
      }
    }

    // hasEmptyState: checks for .length === 0 or !data patterns
    if (Node.isBinaryExpression(desc)) {
      const text = desc.getText();
      if (
        /\.length\s*===?\s*0/.test(text) ||
        (/\.length\s*!==?\s*[^0]/.test(text) === false && /\.length\s*<\s*1/.test(text))
      ) {
        markers.hasEmptyState = true;
      }
    }
    if (
      Node.isPrefixUnaryExpression(desc) &&
      desc.getOperatorToken() === SyntaxKind.ExclamationToken
    ) {
      const operand = desc.getOperand();
      if (Node.isIdentifier(operand)) {
        const name = operand.getText();
        if (/^(data|items|results|entries|records|list|rows)$/i.test(name)) {
          markers.hasEmptyState = true;
        }
      }
    }

    // rendersIteration: .map() in JSX context
    if (Node.isCallExpression(desc)) {
      const expr = desc.getExpression();
      if (Node.isPropertyAccessExpression(expr) && expr.getName() === "map") {
        // Check if ancestor is a JSX expression
        let ancestor: Node | undefined = desc.getParent();
        while (ancestor) {
          if (ancestor.getKind() === SyntaxKind.JsxExpression) {
            markers.rendersIteration = true;
            break;
          }
          if (ancestor.getKind() === SyntaxKind.ReturnStatement) {
            markers.rendersIteration = true;
            break;
          }
          ancestor = ancestor.getParent();
        }
      }

      // sideEffects: useEffect, addEventListener, setTimeout, setInterval
      const callText = desc.getExpression().getText();
      if (/^(useEffect|useLayoutEffect)$/.test(callText)) {
        markers.sideEffects = true;
      }
      if (/addEventListener|setTimeout|setInterval|requestAnimationFrame/.test(callText)) {
        markers.sideEffects = true;
      }
    }

    // rendersConditional: && or ternary in JSX return context
    if (kindNum === SyntaxKind.JsxExpression) {
      const exprChild = desc.getChildAtIndex(1); // The expression inside { }
      if (exprChild) {
        const exprText = exprChild.getText();
        // Pattern: condition && <Jsx> or condition ? <A> : <B>
        if (exprChild.getKind() === SyntaxKind.BinaryExpression) {
          const opToken = exprChild.getChildAtIndex(1);
          if (opToken && opToken.getKind() === SyntaxKind.AmpersandAmpersandToken) {
            markers.rendersConditional = true;
          }
        }
        if (exprChild.getKind() === SyntaxKind.ConditionalExpression) {
          markers.rendersConditional = true;
        }
        // Also handle nested ternaries/&& in the text
        if (!markers.rendersConditional && (/&&/.test(exprText) || /\?.*:/.test(exprText))) {
          markers.rendersConditional = true;
        }
      }
    }
  });

  return markers;
}
