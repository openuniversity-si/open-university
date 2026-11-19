import js from "@eslint/js";
import comments from "@eslint-community/eslint-plugin-eslint-comments/configs";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: [".next/**", ".next-test/**", ".next-production/**", "next-env.d.ts", "test-results/**", "playwright-report/**", ".reports/**"],
  },
  {
    linterOptions: { reportUnusedDisableDirectives: "error" },
  },
  js.configs.recommended,
  ...nextVitals,
  ...nextTs,
  ...tseslint.configs.strictTypeChecked,
  {
    languageOptions: {
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
  },
  {
    files: ["**/*.mjs", "**/*.cjs"],
    ...tseslint.configs.disableTypeChecked,
  },
  // .pnpmfile.cjs: pnpm loads hooks as CommonJS.
  {
    files: ["**/*.cjs"],
    languageOptions: { sourceType: "commonjs", globals: { require: "readonly", module: "writable" } },
    rules: { "@typescript-eslint/no-require-imports": "off" },
  },
  // §10.3: every eslint-disable carries a written justification; no deferred-work markers.
  comments.recommended,
  {
    rules: {
      "@eslint-community/eslint-comments/require-description": ["error", { ignore: [] }],
      "@eslint-community/eslint-comments/no-unlimited-disable": "error",
      "no-warning-comments": ["error", { terms: ["todo", "fixme", "xxx", "hack"], location: "anywhere" }],
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/ban-ts-comment": ["error", { "ts-expect-error": "allow-with-description", "ts-ignore": true, "ts-nocheck": true }],
    },
  },
  // Security (SSDF PW.5, docs/security/SECURE-CODING.md): no string runs as code, no script URL, no unsandboxed
  // frame, no reverse-tabnabbing link, no prototype tampering. Core and eslint-plugin-react rules only, no new package.
  {
    rules: {
      "no-eval": "error",
      "no-new-func": "error",
      "no-script-url": "error",
      "no-proto": "error",
      "no-extend-native": "error",
    },
  },
  {
    files: ["**/*.{js,jsx,mjs,ts,tsx,mts,cts}"],
    rules: {
      "react/jsx-no-script-url": "error",
      "react/jsx-no-target-blank": "error",
      "react/iframe-missing-sandbox": "error",
    },
  },
  // Tests feed javascript: URLs as hostile input to prove the site refuses them.
  {
    files: ["**/*.test.ts", "**/*.test.tsx"],
    rules: { "no-script-url": "off" },
  },
  // §3: UI never reaches the progress repository directly.
  {
    files: ["src/ui/**"],
    rules: {
      "no-restricted-imports": ["error", { patterns: [{ group: ["@/progress/server/repo", "@/progress/server/repo/*", "**/progress/server/repo", "**/progress/server/repo/*"], message: "src/ui must not import the progress repository (§3)." }] }],
    },
  },
  // ADR-11: every E2E spec goes through the no-video guard fixture.
  {
    files: ["e2e/**/*.ts"],
    ignores: ["e2e/fixtures/no-video-guard.ts"],
    rules: {
      "no-restricted-imports": ["error", { paths: [{ name: "@playwright/test", importNames: ["test"], message: "Import `test` from e2e/fixtures/no-video-guard.ts (ADR-11)." }] }],
    },
  },
);
