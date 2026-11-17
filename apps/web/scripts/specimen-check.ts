import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const manifest = async (directory: string): Promise<Record<string, string>> => JSON.parse(await readFile(`${directory}/server/app-paths-manifest.json`, "utf8")) as Record<string, string>;
const [production, test] = await Promise.all([manifest(".next"), manifest(".next-test")]);
// App path manifests retain route groups, which do not appear in the public URL.
const hasRoute = (paths: Record<string, string>, route: string) => Object.keys(paths).some((path) => path.replace(/\/\([^/]+\)/g, "") === `${route}/page`);
for (const route of ["/specimen", "/fixtures/shell", "/fixtures/error", "/fixtures/states"]) {
  assert.equal(hasRoute(production, route), false, `${route} must be absent from production.`);
  assert.equal(hasRoute(test, route), true, `Test build must expose ${route}.`);
}
console.log("specimen:check: test-only routes (/specimen, /fixtures/shell, /fixtures/error, /fixtures/states) absent from production; present in the test build.");
