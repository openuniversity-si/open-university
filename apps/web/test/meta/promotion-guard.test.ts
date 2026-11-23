import { spawnSync } from "node:child_process";
import { chmodSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/** Andon at promotion (D-363): the site image is built only for a commit whose full-suite is green. */
const build = readFileSync(new URL("../../deploy/build-image.sh", import.meta.url), "utf8");
const guard = readFileSync(new URL("../../deploy/promotion-guard.sh", import.meta.url), "utf8");

describe("promotion guard (D-363, D-364)", () => {
  it("is the Torre's step before the build, not a step inside it (D-364)", () => {
    expect(build).not.toContain("promotion-guard.sh\"");
    expect(guard).toContain("aws codebuild start-build");
  });

  it("asks promotion-health about the exact commit's full-suite and fails closed", () => {
    expect(guard).toContain("check_name=full-suite");
    expect(guard).toContain('bash "$root/scripts/workflow-attest" promotion-health --checks "$checks" --sha "$sha"');
    expect(guard).toContain("set -euo pipefail");
    expect(guard).toMatch(/could not be read; not promoting \(fail closed\)"[^\n]*\n\s+exit 1/);
  });

  /** Runs the guard for real with a fake curl on PATH that prints `runs` as the commit's check runs. */
  function guardWith(runs: object[] | null) {
    const bin = mkdtempSync(join(tmpdir(), "guard-"));
    const curl = join(bin, "curl");
    const body = runs === null ? "exit 22" : `cat <<'JSON'\n${JSON.stringify({ check_runs: runs })}\nJSON`;
    writeFileSync(curl, `#!/usr/bin/env bash\n${body}\n`);
    chmodSync(curl, 0o755);
    const script = fileURLToPath(new URL("../../deploy/promotion-guard.sh", import.meta.url));
    return spawnSync("bash", [script, sha], { env: { ...process.env, PATH: `${bin}:${process.env.PATH ?? ""}` }, encoding: "utf8" });
  }
  const sha = "b".repeat(40);
  const suite = (conclusion: string | null, status = "completed") => ({ id: 1, name: "full-suite", head_sha: sha, status, conclusion });

  it("runs end to end: green passes, red, running or unreadable refuse", () => {
    expect(guardWith([suite("success")]).status).toBe(0);
    expect(guardWith([suite("failure")]).status).toBe(1);
    expect(guardWith([suite(null, "in_progress")]).status).toBe(1);
    const unreadable = guardWith(null);
    expect(unreadable.status).toBe(1);
    expect(unreadable.stderr).toContain("fail closed");
  });
});
