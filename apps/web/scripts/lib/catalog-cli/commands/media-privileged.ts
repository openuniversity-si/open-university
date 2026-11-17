import { spawn } from "node:child_process";
import { join } from "node:path";

/** Privileged content migration. Normal put/check never reach this module. */
export function runContentMigration(args: readonly string[], appRoot: string): Promise<number> {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [join(appRoot, "scripts/media-content-migrate.ts"), ...args], { stdio: "inherit" });
    child.on("error", () => { resolve(127); });
    child.on("close", (code) => { resolve(code ?? 1); });
  });
}
