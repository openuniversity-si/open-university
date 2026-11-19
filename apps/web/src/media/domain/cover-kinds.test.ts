import { readdirSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { coverKindsByOwner, coverOwners } from "../../kernel/cover-kinds.ts";
import { coverOwnerKindSql } from "../../platform/db/schema.ts";
import { coverKindAllowed } from "./cover-choice.ts";
import { mediaKey, ownerSchema } from "./types.ts";

// Verifies: D-035
// D-035: one list, in the kernel, because the database check reads it there. The figure refuses.

describe("cover kinds (D-035)", () => {
  it("refuses a kind the owner does not accept", () => {
    expect(coverKindAllowed("lesson", "still_16x9")).toBe(false);
    expect(coverKindAllowed("subarea", "still_16x9")).toBe(false);
    expect(() => mediaKey("lesson", "lesson-1", "still_16x9")).toThrow();
    expect(() => mediaKey("subarea", "mechanics", "still_16x9")).toThrow();
  });

  it("D-035: one cover-kind list", () => {
    expect([...ownerSchema.options]).toEqual([...coverOwners]);
    expect(mediaKey("area", "physics", "still_16x9").kind).toBe("still_16x9");
    expect(() => mediaKey("subarea", "mechanics", "still_16x9")).toThrow();
    expect(coverKindAllowed("area", "still_16x9")).toBe(true);
    expect(coverKindAllowed("subarea", "still_16x9")).toBe(false);

    const schema = readFileSync(new URL("../../platform/db/schema.ts", import.meta.url), "utf8");
    expect(schema).toContain('coverOwnerKindSql("catalog_media")');
    expect(schema).not.toContain("catalog_media_kind");
    const sql = readdirSync(new URL("../../../drizzle", import.meta.url))
      .filter((name) => name >= "0031" && name.endsWith(".sql"))
      .map((name) => readFileSync(new URL(`../../../drizzle/${name}`, import.meta.url), "utf8"))
      .join("\n");
    const expected = coverOwners.flatMap((owner) => coverKindsByOwner[owner].map((kind) => `${owner}:${kind}`)).sort();
    const found = [...new Set([...sql.matchAll(/\('([a-z0-9_]+)', '([a-z0-9_]+)'\)/g)].map((match) => `${match[1] ?? ""}:${match[2] ?? ""}`))].sort();
    expect(found).toEqual(expected);
    expect(sql).toContain(coverOwnerKindSql("catalog_media"));
    expect(sql).toContain('DELETE FROM "catalog_media"');
    expect(sql).not.toContain("('subarea', 'still_16x9')");
  });
});
