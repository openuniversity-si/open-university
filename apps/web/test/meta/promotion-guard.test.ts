import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

/** Andon at promotion (D-363): the site image is built only for a commit whose full-suite is green. */
const build = readFileSync(new URL("../../deploy/build-image.sh", import.meta.url), "utf8");
const guard = readFileSync(new URL("../../deploy/promotion-guard.sh", import.meta.url), "utf8");

describe("promotion guard (D-363)", () => {
  it("runs before anything is installed or built, for a release (BUILD_SHA set)", () => {
    const call = build.indexOf('bash "$web/deploy/promotion-guard.sh" "$BUILD_SHA"');
    expect(call).toBeGreaterThan(-1);
    expect(build.lastIndexOf('if [[ -n "${BUILD_SHA:-}" ]]', call)).toBeGreaterThan(-1);
    expect(call).toBeLessThan(build.indexOf("pnpm install"));
  });

  it("asks promotion-health about the exact commit's full-suite and fails closed", () => {
    expect(guard).toContain("check_name=full-suite");
    expect(guard).toContain('scripts/workflow-attest" promotion-health --checks "$checks" --sha "$sha"');
    expect(guard).toContain("set -euo pipefail");
    expect(guard).toMatch(/could not be read; not promoting \(fail closed\)"[^\n]*\n\s+exit 1/);
  });
});
