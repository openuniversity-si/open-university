import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const webRoot = fileURLToPath(new URL("../../../", import.meta.url));

describe("object port names", () => {
  it("keeps vendor endpoints inside their adapters", () => {
    const port = readFileSync(join(webRoot, "src/media/ports/storage.ts"), "utf8");
    const bucket = readFileSync(join(webRoot, "src/media/server/r2.ts"), "utf8");
    const schema = readFileSync(join(webRoot, "src/platform/db/schema.ts"), "utf8");
    expect(port.includes("blob")).toBe(false);
    expect(port.includes("r2")).toBe(false);
    expect(bucket.includes("cf-copy-destination-if-none-match")).toBe(true);
    expect(bucket.includes("r2.cloudflarestorage.com")).toBe(true);
    expect(schema.includes("r2_pending_deletions")).toBe(true);
  });
});
