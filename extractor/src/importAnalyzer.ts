import { SourceFile, Node } from "ts-morph";
import type { ImportEntry, ImportInfo } from "./types.js";

/** Framework packages that get their own import category. */
const FRAMEWORK_PACKAGES = new Set([
  "react",
  "react-dom",
  "react-dom/client",
  "react/jsx-runtime",
  "zustand",
  "zustand/middleware",
  "zustand/shallow",
  "dexie",
  "dexie-react-hooks",
  "@tanstack/react-query",
  "@tanstack/react-table",
  "@tanstack/react-virtual",
  "@tanstack/react-router",
]);

function isFrameworkImport(source: string): boolean {
  if (FRAMEWORK_PACKAGES.has(source)) return true;
  // @tanstack/* wildcard
  if (source.startsWith("@tanstack/")) return true;
  // react-* packages
  if (source === "react" || source.startsWith("react-dom")) return true;
  return false;
}

function isInternalImport(source: string): boolean {
  return source.startsWith(".") || source.startsWith("@/") || source.startsWith("~/");
}

function categorizeImport(source: string): ImportEntry["category"] {
  if (isFrameworkImport(source)) return "framework";
  if (isInternalImport(source)) return "internal";
  return "external";
}

/**
 * Analyze all imports in a source file.
 * Also detects store access patterns and data source access.
 */
// eslint-disable-next-line sonarjs/cognitive-complexity -- classifies imports across multiple categories and patterns
export function analyzeImports(sourceFile: SourceFile, _projectRoot: string): ImportInfo {
  const imports: ImportEntry[] = [];
  const storeAccess: string[] = [];
  const dataSourceAccess: string[] = [];

  // Process import declarations
  for (const decl of sourceFile.getImportDeclarations()) {
    const source = decl.getModuleSpecifierValue();
    const specifiers: string[] = [];

    // Default import
    const defaultImport = decl.getDefaultImport();
    if (defaultImport) {
      specifiers.push(defaultImport.getText());
    }

    // Named imports
    for (const named of decl.getNamedImports()) {
      const alias = named.getAliasNode();
      specifiers.push(alias ? `${named.getName()} as ${alias.getText()}` : named.getName());
    }

    // Namespace import
    const nsImport = decl.getNamespaceImport();
    if (nsImport) {
      specifiers.push(`* as ${nsImport.getText()}`);
    }

    imports.push({
      source,
      specifiers,
      category: categorizeImport(source),
    });
  }

  // Detect store access patterns in the full file text
  const fullText = sourceFile.getFullText();

  // useXxxStore() calls
  const storeCallPattern = /\buse(\w+Store)\s*\(/g;
  let match: RegExpExecArray | null;
  const seenStores = new Set<string>();
  while ((match = storeCallPattern.exec(fullText)) !== null) {
    const storeName = `use${match[1]}`;
    if (!seenStores.has(storeName)) {
      seenStores.add(storeName);
      storeAccess.push(storeName);
    }
  }

  // store.getState() / store.setState() patterns
  const storeGetSetPattern = /\b(\w+Store)\.(getState|setState|subscribe)\s*\(/g;
  while ((match = storeGetSetPattern.exec(fullText)) !== null) {
    const access = `${match[1]}.${match[2]}`;
    if (!seenStores.has(access)) {
      seenStores.add(access);
      storeAccess.push(access);
    }
  }

  // Data source access patterns
  const seenDataSources = new Set<string>();

  // Dexie: db.tableName patterns
  const dbTablePattern = /\bdb\.(\w+)\b/g;
  while ((match = dbTablePattern.exec(fullText)) !== null) {
    const access = `db.${match[1]}`;
    if (!seenDataSources.has(access)) {
      seenDataSources.add(access);
      dataSourceAccess.push(access);
    }
  }

  // useLiveQuery calls
  if (/\buseLiveQuery\s*\(/.test(fullText)) {
    if (!seenDataSources.has("useLiveQuery")) {
      seenDataSources.add("useLiveQuery");
      dataSourceAccess.push("useLiveQuery");
    }
  }

  // fetch() calls
  sourceFile.forEachDescendant((node) => {
    if (Node.isCallExpression(node)) {
      const expr = node.getExpression();
      if (Node.isIdentifier(expr) && expr.getText() === "fetch") {
        if (!seenDataSources.has("fetch")) {
          seenDataSources.add("fetch");
          dataSourceAccess.push("fetch");
        }
      }
    }
  });

  return { imports, storeAccess, dataSourceAccess };
}
