import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { SIGNED_IN_HOME_PATH } from "../src/site/domain/home-routing.ts";
import { staticHomeFailures } from "./lib/static-home.ts";
import { assertDirectImages } from "./lib/direct-images.ts";

/** Runs after `next build` (both targets): fails the build if `/` turned dynamic or the signed-in Home got cached. */
const distDir = process.env.TOWER_DIST_DIR ?? (process.env.TOWER_BUILD_TARGET === "test" ? ".next-test" : ".next");
const manifest = JSON.parse(readFileSync(path.resolve(import.meta.dirname, "..", distDir, "prerender-manifest.json"), "utf8")) as Parameters<typeof staticHomeFailures>[0];
const failures = staticHomeFailures(manifest, SIGNED_IN_HOME_PATH);
for (const failure of failures) console.error(`static-home: ${failure}`);
if (failures.length) process.exit(1);
console.log("static-home: / is ISR; the signed-in Home is dynamic.");

const build = path.resolve(import.meta.dirname, "..", distDir);
const { config } = JSON.parse(readFileSync(path.join(build, "required-server-files.json"), "utf8")) as { config: Parameters<typeof assertDirectImages>[0] };
assertDirectImages(config, "");
for (const file of readdirSync(path.join(build, "server", "app"), { recursive: true })) {
  if (typeof file === "string" && file.endsWith(".html")) assertDirectImages(config, readFileSync(path.join(build, "server", "app", file), "utf8"));
}
console.log("direct-images: optimizer disabled; generated HTML contains no transformation URLs.");
