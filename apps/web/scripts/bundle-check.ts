import { spawn } from "node:child_process";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { gzipSync } from "node:zlib";
import { PAGE_ROUTES } from "../e2e/routes.ts";
import { ENGINE_MARKERS } from "../src/playback/domain/markers.ts";
import { extractScriptPaths, findSecretLeaks, frameworkScriptPaths, HOME_INITIAL_JS_BUDGET_BYTES, INITIAL_JS_BUDGET_BYTES } from "./lib/bundle-scan.ts";

/**
 * bundle:check, run after `pnpm build` and `pnpm build:test`:
 * 1. §10.4 budget: the app's own initial JS (gzip, Next runtime excluded) of every page route of the production build,
 *    and the tighter Home budget (HOME_INITIAL_JS_BUDGET_BYTES);
 * 2. §11.1: no secret names, key patterns or secret values in client bundles of either build;
 * 3. ADR-11: production contains only the YouTube engine, the test build only the fake one; neither ships mux-video.
 */
const root = path.resolve(import.meta.dirname, "..");
// TOWER_BUNDLE_PORT: another checkout may already hold the default port.
const PORT = Number(process.env.TOWER_BUNDLE_PORT ?? 3199);
const failures: string[] = [];

async function listFiles(dir: string): Promise<string[]> {
  const entries = await readdir(dir, { withFileTypes: true, recursive: true });
  return entries.filter((e) => e.isFile()).map((e) => path.join(e.parentPath, e.name));
}

async function filesContaining(dir: string, needle: string): Promise<number> {
  let count = 0;
  for (const file of await listFiles(dir)) {
    if (!/\.(js|mjs|cjs|html|rsc|json)$/.test(file)) continue;
    if ((await readFile(file, "utf8")).includes(needle)) count += 1;
  }
  return count;
}

async function checkEngine(distDir: string, expected: keyof typeof ENGINE_MARKERS): Promise<void> {
  const dir = path.join(root, distDir);
  for (const [engine, marker] of Object.entries(ENGINE_MARKERS)) {
    const files = await filesContaining(dir, marker);
    console.log(`engine ${distDir}: ${engine}=${String(files)} file(s)`);
    if (engine === expected && files === 0) failures.push(`${distDir} does not contain the ${engine} engine`);
    if (engine !== expected && files > 0) failures.push(`${distDir} contains the ${engine} engine`);
  }
  // The Mux engine is paused: its media element ships in neither build.
  const muxVideo = await filesContaining(path.join(dir, "static"), '"mux-video"');
  console.log(`mux-video ${distDir}/static: ${String(muxVideo)} file(s)`);
  if (muxVideo > 0) failures.push(`${distDir} contains mux-video`);
}

async function checkSecrets(distDir: string): Promise<void> {
  const files = await listFiles(path.join(root, distDir, "static"));
  let leaks = 0;
  for (const file of files) {
    if (!/\.(js|mjs|css|map|json|txt)$/.test(file)) continue;
    for (const finding of findSecretLeaks(await readFile(file, "utf8"), process.env)) {
      leaks += 1;
      failures.push(`${path.relative(root, file)}: ${finding}`);
    }
  }
  console.log(`secrets ${distDir}/static: ${String(files.length)} file(s) scanned, ${String(leaks)} finding(s)`);
}

async function waitForServer(url: string): Promise<void> {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {
      // Server not listening yet.
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`server did not start: ${url}`);
}

async function checkBudget(): Promise<void> {
  const nextBin = path.join(root, "node_modules/next/dist/bin/next");
  const server = spawn(process.execPath, [nextBin, "start", "--port", String(PORT), "--hostname", "127.0.0.1"], {
    cwd: root,
    env: { ...process.env, TOWER_BUILD_TARGET: "production" },
    stdio: "ignore",
  });
  const manifest = JSON.parse(await readFile(path.join(root, ".next/build-manifest.json"), "utf8")) as { rootMainFiles?: string[] };
  const framework = frameworkScriptPaths(manifest);
  try {
    const base = `http://127.0.0.1:${String(PORT)}`;
    await waitForServer(`${base}/api/health`);
    for (const route of PAGE_ROUTES) {
      const html = await (await fetch(`${base}${route}`)).text();
      const scripts = extractScriptPaths(html);
      let runtime = 0;
      let own = 0;
      for (const src of scripts) {
        const size = gzipSync(await readFile(path.join(root, ".next", src.replace(/^\/_next\//, "")))).length;
        if (framework.has(src)) runtime += size;
        else own += size;
      }
      const kb = (bytes: number): string => (bytes / 1024).toFixed(1);
      console.log(
        `budget ${route}: own ${kb(own)} KB gzip (limit ${kb(INITIAL_JS_BUDGET_BYTES)} KB) + Next runtime ${kb(runtime)} KB = ${kb(own + runtime)} KB initial JS in ${String(scripts.length)} script(s)`,
      );
      if (scripts.length === 0 || runtime === 0) failures.push(`${route}: scripts not found in HTML (measurement broken)`);
      if (own > INITIAL_JS_BUDGET_BYTES) failures.push(`${route}: own initial JS ${kb(own)} KB gzip exceeds the budget`);
      if (route === "/" && own > HOME_INITIAL_JS_BUDGET_BYTES) failures.push(`/: own initial JS ${kb(own)} KB gzip exceeds the Home budget of ${kb(HOME_INITIAL_JS_BUDGET_BYTES)} KB`);
    }
  } finally {
    server.kill();
  }
}

await checkEngine(".next", "youtube");
await checkEngine(".next-test", "fake");
await checkSecrets(".next");
await checkSecrets(".next-test");
await checkBudget();

for (const failure of failures) console.error(`FAIL: ${failure}`);
console.log(failures.length === 0 ? "bundle:check: PASS" : `bundle:check: FAIL (${String(failures.length)})`);
process.exitCode = failures.length === 0 ? 0 : 1;
