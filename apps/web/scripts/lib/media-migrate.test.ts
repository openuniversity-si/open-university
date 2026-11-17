import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import sharp from "sharp";
import { describe, expect, it } from "vitest";
import { copyObjects, indexLocalFiles, mergeUrlMaps, planHostRewrite, planMigration, type MediaRow } from "./media-migrate.ts";
import { createFsMediaStore } from "./media-storage.ts";
import "../../src/media/server/public-hosts.ts";
import { MEDIA_PUBLIC_HOST, mediaPublicHosts, mediaUrlSchema, mediaUrlSchemaFor } from "../../src/media/domain/types.ts";

const host = `pub-${"b".repeat(32)}.r2.dev`;
process.env.TOWER_MEDIA_PUBLIC_HOST = host;
const legacyHost = "legacy-media.example";
const row = (id: string, sha: string, path = `covers/course-1/thumb/${sha.slice(0, 40)}.png`): MediaRow => ({ table: "catalog_media", id, url: `https://${legacyHost}/${path}`, pathname: path, sha256: sha, width: 4, height: 4 });

describe("media hosts", () => {
  it("defaults to the one public host and accepts only the bucket's r2.dev bridge as an override", () => {
    expect(mediaPublicHosts({})).toEqual([MEDIA_PUBLIC_HOST]);
    expect(MEDIA_PUBLIC_HOST).toBe("media.openuniversity.si");
    expect(mediaPublicHosts(process.env)).toEqual([host]); // this file's override
    expect(mediaUrlSchemaFor(mediaPublicHosts(process.env)).safeParse(`https://${host}/covers/a/thumb/b.png`).success).toBe(true);
    expect(mediaUrlSchema.safeParse(`https://pub-${"c".repeat(32)}.r2.dev/covers/a/thumb/b.png`).success).toBe(false);
    expect(() => mediaPublicHosts({ TOWER_MEDIA_PUBLIC_HOST: "evil.example" })).toThrow();
  });
  it("has no list of previous hosts: the retired media.thetower.si and the old setting are refused", () => {
    expect(() => mediaPublicHosts({ TOWER_MEDIA_PUBLIC_HOST: "media.thetower.si" })).toThrow();
    expect(mediaPublicHosts({ TOWER_MEDIA_PREVIOUS_HOSTS: host })).toEqual([MEDIA_PUBLIC_HOST]);
    expect(mediaUrlSchema.safeParse("https://media.thetower.si/covers/a/thumb/b.png").success).toBe(false);
  });
});

describe("host-only rewrite plan", () => {
  it("moves every row not on the host, once per row, and lists each pathname once", () => {
    const a = "a".repeat(64);
    const old = { ...row("1", a), url: `https://${legacyHost}/${row("1", a).pathname}` };
    const there = { ...row("2", a), url: `https://${host}/${row("2", a).pathname}` };
    const plan = planHostRewrite([old, there], host);
    expect(plan.rewrites).toEqual([{ table: "catalog_media", id: "1", oldUrl: old.url, newUrl: `https://${host}/${old.pathname}` }]);
    expect(plan.pathnames).toEqual([old.pathname]);
    expect(() => planHostRewrite([{ ...old, pathname: "covers/other/thumb/x.png" }], host)).toThrow();
  });
});

describe("R2 migration plan", () => {
  it("refuses missing shas, rewrites only the host, keeps the first URL map", () => {
    const a = "a".repeat(64), b = "b".repeat(64);
    const plan = planMigration([row("1", a), row("2", a), row("3", b)], new Map([[a, "/tmp/a"]]), host);
    expect(plan.missing).toEqual([b]);
    expect(plan.objects).toHaveLength(1);
    expect(plan.rewrites[0]?.newUrl).toBe(`https://${host}/${row("1", a).pathname}`);
    expect(planMigration([{ ...row("1", a), url: `https://${host}/${row("1", a).pathname}` }], new Map([[a, "/tmp/a"]]), host).rewrites).toEqual([]);
    expect(() => planMigration([{ ...row("1", a), pathname: "covers/other/thumb/x.png" }], new Map(), host)).toThrow();
    const first = { host, entries: [{ table: "catalog_media" as const, id: "1", oldUrl: "old", newUrl: "new" }] };
    expect(mergeUrlMaps(first, { host, entries: [{ table: "catalog_media", id: "1", oldUrl: "new", newUrl: "new" }] }).entries[0]?.oldUrl).toBe("old");
  });
  it("indexes local files by content and copies each object once, refusing different stored bytes", async () => {
    const dir = await mkdtemp(resolve(tmpdir(), "tower-migrate-test-"));
    try {
      const bytes = await sharp({ create: { width: 4, height: 4, channels: 3, background: "red" } }).png().toBuffer();
      const sha = createHash("sha256").update(bytes).digest("hex");
      await writeFile(resolve(dir, "original-name.png"), bytes);
      const index = await indexLocalFiles([dir]);
      const rows = [row("1", sha)];
      const plan = planMigration(rows, index, host);
      const store = createFsMediaStore(resolve(dir, "store"), host);
      expect(await copyObjects(plan, store, rows)).toEqual({ uploaded: 1, present: 0 });
      expect(await copyObjects(plan, store, rows)).toEqual({ uploaded: 0, present: 1 });
      await writeFile(resolve(dir, "store", rows[0]?.pathname ?? ""), "tampered");
      await expect(copyObjects(plan, store, rows)).rejects.toThrow(/differs/);
    } finally { await rm(dir, { recursive: true, force: true }); }
  });
});
