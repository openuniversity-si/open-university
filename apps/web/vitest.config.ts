import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const src = fileURLToPath(new URL("./src", import.meta.url));
// The gate points this at a directory keyed by the lockfile and the vitest version.
// Unset, vitest keeps its cache inside node_modules, which the worktree never reuses.
const vitestCache = process.env.OU_VITEST_CACHE || "node_modules/.vite";

const SLUG_FILES = ["src/catalog/domain/lesson-address.ts", "src/catalog/domain/slug-course.ts", "src/catalog/domain/lesson-slug.ts", "scripts/lib/slug-redirects.ts"];

export default defineConfig({
  cacheDir: vitestCache,
  resolve: {
    alias: [
      // Unit tests import server modules the same way integration tests do. The throw is for client bundles.
      { find: "server-only", replacement: fileURLToPath(new URL("./test/server-only-stub.ts", import.meta.url)) },
      { find: "@tower/playback-engine", replacement: `${src}/playback/client/youtube.ts` },
      { find: "@tower/catalog", replacement: `${src}/catalog/testing/fake.ts` },
      // Pages read through the port. Unit tests keep the fake release instead of opening server-only SQL.
      { find: "@/catalog/server/page-reads", replacement: `${src}/catalog/testing/page-reads.ts` },
      { find: /^@\//, replacement: `${src}/` },
    ],
  },
  test: {
    // `pnpm test` enforces full coverage of the pure progress rules (F11) and ≥ 90 % of the lesson slug rule, its course-wide
    // form, the batch planner and the redirect verifier (P7).
    coverage: {
      provider: "v8", include: ["src/progress/domain/rules.ts", ...SLUG_FILES], reporter: ["text-summary"],
      thresholds: { "src/progress/domain/rules.ts": { 100: true }, ...Object.fromEntries(SLUG_FILES.map((file) => [file, { lines: 90, branches: 90, functions: 90, statements: 90 }])) },
    },
    projects: [
      {
        extends: true,
        test: {
          name: "unit",
          // Leave CPU/memory for the integration critical path and both builds in the full gate.
          maxWorkers: 2,
          include: ["src/**/*.test.ts", "scripts/**/*.test.ts", "fidelity/**/*.test.ts", "e2e/fixtures/**/*.test.ts", "test/**/*.test.ts"],
          exclude: ["**/*.int.test.ts"],
          environment: "node",
        },
      },
      {
        extends: true,
        resolve: {
          alias: [
            { find: "server-only", replacement: fileURLToPath(new URL("./test/server-only-stub.ts", import.meta.url)) },
            { find: "@tower/playback-engine", replacement: `${src}/playback/client/youtube.ts` },
            { find: "@tower/catalog", replacement: `${src}/catalog/testing/fake.ts` },
            { find: "@/catalog/server/page-reads", replacement: `${src}/catalog/testing/page-reads.ts` },
            { find: /^@\//, replacement: `${src}/` },
          ],
        },
        test: {
          name: "int",
          // Every file gets a fresh clone of the migrated local template (including destructive migration tests).
          maxWorkers: 4,
          setupFiles: ["./test/int-database.ts"],
          include: ["**/*.int.test.ts"],
          globalSetup: ["./test/int-teardown.ts"],
          // Every case reseeds the shared PG18 in beforeEach; on a loaded shared box (load ~16) that exceeded the 10 s default.
          hookTimeout: 60_000,
          testTimeout: 60_000,
          exclude: ["node_modules/**"],
          environment: "node",
        },
      },
    ],
  },
});
