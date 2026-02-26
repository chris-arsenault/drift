import { Node } from "ts-morph";
import type { HookInfo, HookCallEntry } from "./types.js";

/** React built-in hooks (not custom). */
const REACT_BUILT_IN_HOOKS = new Set([
  "useState",
  "useEffect",
  "useCallback",
  "useMemo",
  "useRef",
  "useContext",
  "useReducer",
  "useLayoutEffect",
  "useDeferredValue",
  "useTransition",
  "useId",
  "useSyncExternalStore",
  "useInsertionEffect",
  "useImperativeHandle",
  "useDebugValue",
]);

/**
 * Analyze hook usage within a function/component body.
 *
 * Finds all call expressions where the callee name starts with `use` (React convention).
 * Counts occurrences, categorizes built-in vs custom, and counts state variables.
 */
export function analyzeHooks(node: Node): HookInfo {
  const hookCounts = new Map<string, number>();
  const customHookSet = new Set<string>();
  let stateVariableCount = 0;

  node.forEachDescendant((desc) => {
    if (!Node.isCallExpression(desc)) return;

    const expr = desc.getExpression();
    let hookName: string | null = null;

    // Direct call: useFoo()
    if (Node.isIdentifier(expr)) {
      const name = expr.getText();
      if (name.startsWith("use") && name.length > 3 && name[3] === name[3].toUpperCase()) {
        hookName = name;
      }
    }

    // Namespaced call: React.useState()
    if (Node.isPropertyAccessExpression(expr)) {
      const propName = expr.getName();
      if (
        propName.startsWith("use") &&
        propName.length > 3 &&
        propName[3] === propName[3].toUpperCase()
      ) {
        hookName = propName;
      }
    }

    if (!hookName) return;

    // Count occurrences
    hookCounts.set(hookName, (hookCounts.get(hookName) ?? 0) + 1);

    // Classify as custom if not a React built-in
    if (!REACT_BUILT_IN_HOOKS.has(hookName)) {
      customHookSet.add(hookName);
    }

    // Count state variables from useState destructuring:
    // const [value, setValue] = useState(...)
    if (hookName === "useState") {
      const parent = desc.getParent();
      if (parent && Node.isVariableDeclaration(parent)) {
        const nameNode = parent.getNameNode();
        if (Node.isArrayBindingPattern(nameNode)) {
          // Standard pattern: [value, setValue] = one state variable
          stateVariableCount += 1;
        }
      }
    }
  });

  // Build ordered hookCalls list (ordered by first appearance - Map preserves insertion order)
  const hookCalls: HookCallEntry[] = [];
  for (const [name, count] of hookCounts) {
    hookCalls.push({ name, count });
  }

  return {
    hookCalls,
    customHookCalls: [...customHookSet].sort(),
    stateVariableCount,
  };
}
