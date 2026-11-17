import { execFileSync } from "node:child_process";
import { rejectedRasterFiles } from "./lib/repo-assets.ts";

// Only this app's tracked files; --full-name keeps the repository-relative apps/web/... paths the allowlist names.

const tracked = execFileSync("git", ["ls-files", "-z", "--full-name"], { cwd: new URL("..", import.meta.url), encoding: "utf8" }).split("\0").filter(Boolean);
const rejected = rejectedRasterFiles(tracked);
if (rejected.length) {
  console.error(`Tracked raster media must live in object storage (R2), not git:\n${rejected.join("\n")}`); process.exitCode = 1;
} else console.log("Repository assets: no tracked raster images outside the brand/OG/UI icon allowlist.");
