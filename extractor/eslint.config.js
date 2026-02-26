import js from "@eslint/js";
import globals from "globals";
import sonarjs from "eslint-plugin-sonarjs";
import prettier from "eslint-config-prettier";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: ["node_modules/", "dist/"],
  },

  // Base JS rules + complexity limits
  {
    ...js.configs.recommended,
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
    },
    rules: {
      complexity: ["warn", 10],
      "max-lines": ["warn", { max: 400, skipBlankLines: true, skipComments: true }],
      "max-lines-per-function": ["warn", { max: 75, skipBlankLines: true, skipComments: true }],
      "max-depth": ["warn", 4],
    },
  },

  // TypeScript: recommended rules
  ...tseslint.configs.recommended,

  // TypeScript source files
  {
    files: ["src/**/*.ts"],
    languageOptions: {
      globals: {
        ...globals.node,
        ...globals.es2025,
      },
    },
    rules: {
      "@typescript-eslint/no-unused-vars": ["warn", { argsIgnorePattern: "^_" }],
      "no-unused-vars": "off",
    },
  },

  // SonarJS — with overrides for AST processing code
  {
    ...sonarjs.configs.recommended,
    rules: {
      ...sonarjs.configs.recommended.rules,
      // AST walkers are inherently complex — these functions process deeply nested trees
      "sonarjs/cognitive-complexity": ["warn", 30],
      // Regex patterns are used on identifiers, not user input
      "sonarjs/slow-regex": "off",
      // Duplicate branches happen in type-narrowing patterns
      "sonarjs/no-duplicated-branches": "warn",
    },
  },

  // Prettier must be last
  prettier
);
