import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import sharp from "sharp";
import { describe, expect, it } from "vitest";
import { prepareMedia } from "../../src/media/server/prepare.ts";
import { batchFromDirectory } from "./batch-from-dir.ts";

describe("batchFromDirectory (S07)", () => {
  it("reads a v1 bundles directory and addresses each cover by its prepared bytes", async () => {
    const directory = mkdtempSync(join(tmpdir(), "batch-v1-"));
    mkdirSync(join(directory, "mechanics"));
    const poster = join(directory, "mechanics/poster.png");
    writeFileSync(poster, await sharp({ create: { width: 9, height: 16, channels: 3, background: "#123456" } }).png().toBuffer());
    writeFileSync(join(directory, "mechanics.json"), JSON.stringify({
      version: 1, author: { id: "ann-lee", slug: "ann-lee", name: "Ann Lee", monogram: "AL", kind: "person" }, home: { rowId: "mit", expectedRevision: 1 },
      course: { id: "mechanics", slug: "mechanics", title: "Mechanics", authorId: "ann-lee", coverFrom: "own", sharedWith: [] },
      editions: [{ id: "mechanics-e", slug: "original", label: "Original", position: 1, year: 2020 }], covers: [{ kind: "poster_9x16", path: "mechanics/poster.png" }],
    }));
    writeFileSync(join(directory, "notes.txt"), "ignored");
    const converted = await batchFromDirectory(directory, new Map([["mit", "mit"]]));
    if (!converted.ok) throw new Error(converted.failures.join("\n"));
    expect(converted.batch.courses[0]?.covers).toEqual([{ kind: "poster_9x16", sha: (await prepareMedia(poster)).sha256 }]);
    expect(converted.batch.courses[0]?.institutionId).toBe("mit");
  });

  it("reports an invalid bundle and a missing cover file together", async () => {
    const directory = mkdtempSync(join(tmpdir(), "batch-v1-"));
    writeFileSync(join(directory, "a.json"), JSON.stringify({ version: 1 }));
    writeFileSync(join(directory, "b.json"), JSON.stringify({
      version: 1, author: { id: "mit", slug: "mit", name: "MIT", monogram: "M", kind: "institution" },
      course: { id: "b", slug: "b", title: "B", authorId: "mit", coverFrom: "own", sharedWith: [] }, editions: [{ id: "b-e", slug: "original", label: "Original", position: 1, year: 2020 }],
      covers: [{ kind: "poster_9x16", path: "missing.png" }],
    }));
    const converted = await batchFromDirectory(directory, new Map());
    expect(converted.ok).toBe(false);
    if (converted.ok) return;
    expect(converted.failures).toHaveLength(3);
    expect(converted.failures[0]).toMatch(/^a\.json: /);
    expect(converted.failures[1]).toMatch(/^b\.json: cover missing\.png: /);
  });
});
