import { describe, expect, it } from "vitest";
import type { UnitOfWork } from "../../platform/db/uow.ts";
import type { AssetInput } from "../domain/types.ts";
import { deleteMedia, listActiveMedia, listMediaByOwners, readActiveCourseMedia, readActiveMedia, rollbackMedia, swapMedia } from "./repository.ts";

const sha = "a".repeat(64);
const external = "https://media.openuniversity.si/covers/course-1/poster_9x16/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.jpg";

function asset(overrides: Record<string, unknown> = {}) {
  return {
    id: "asset-1", ownerId: "course-1", kind: "poster_9x16", variant: "default",
    url: `https://media.openuniversity.si/m/${sha}.webp`, pathname: `m/${sha}.webp`, mediaSha256: sha,
    width: 9, height: 16, sha256: sha, alt: "Cover", transform: null, designStatus: "approved",
    version: 1, isActive: true, createdAt: "2026-01-01T00:00:00.000Z", updatedAt: "2026-01-01T00:00:00.000Z",
    ...overrides,
  };
}

function database(answer: (sql: string) => Record<string, unknown>[]) {
  const sql: string[] = [];
  const locks: string[] = [];
  const tx = {
    query(statement: string) {
      sql.push(statement);
      return Promise.resolve({ rows: answer(statement) });
    },
    acquireLock(lock: { scope: string; mode?: string; key?: string }) {
      locks.push(`${lock.scope}:${lock.mode ?? lock.key ?? ""}`);
      return Promise.resolve();
    },
    onAfterCommit() {},
  };
  return { tx: tx as UnitOfWork, sql, locks };
}

describe("media owners", () => {
  it("returns every named owner from one query, with an empty list when that owner has no rows", async () => {
    const poster = asset({ ownerId: "programming" });
    const db = database((sql) => sql.includes("unnest") ? [{ ...poster, ownerKind: "subarea" }] : []);
    const listed = await listMediaByOwners(db.tx, [
      { owner: "subarea", ownerId: "programming" },
      { owner: "subarea", ownerId: "calculus" },
    ], { activeOnly: true });
    expect(db.sql).toHaveLength(1);
    expect(listed.map((group) => [group.ownerId, group.assets.length])).toEqual([["programming", 1], ["calculus", 0]]);
    expect(listed[0]?.assets[0]?.sha256).toBe(sha);
  });
});

describe("media projection", () => {
  it("joins media_objects and qualifies every reader, including an external url", async () => {
    const course = database(() => [asset()]);
    const externalDb = database(() => [asset({ url: external, pathname: "covers/course-1/poster_9x16/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.jpg", mediaSha256: null })]);
    const active = await readActiveMedia(course.tx, "course", "course-1");
    const outside = await readActiveMedia(externalDb.tx, "course", "course-1");
    const inventory = database((sql) => sql.includes("owner_kind='course'") ? [asset()] : sql.includes("owner_kind='lesson'") ? [asset({ ownerId: "lesson-1", kind: "cover_16x9" })] : [asset({ ownerId: "subarea-1", kind: "og" })]);
    await listActiveMedia(inventory.tx);
    await readActiveCourseMedia(course.tx);
    const joined = [...course.sql, ...externalDb.sql, ...inventory.sql].join("\n");
    expect(joined).toContain("LEFT JOIN media_objects mo ON mo.sha256 = a.media_sha256");
    expect(joined).not.toMatch(/SELECT\s+ext\s+FROM\s+media_objects/i);
    expect(joined).toContain("a.is_active");
    expect(active[0]?.pathname).toBe(`m/${sha}.webp`);
    expect(outside[0]?.url).toBe(external);
    expect(inventory.sql.filter((sql) => sql.includes("FROM catalog_media"))).toHaveLength(5);
  });

  it("returns the same asset dto from insert-then-select and from rollback", async () => {
    const input: AssetInput = {
      ownerId: "course-1", kind: "poster_9x16", variant: "default",
      url: `https://media.openuniversity.si/m/${sha}.webp`, pathname: `m/${sha}.webp`, mediaSha256: sha,
      width: 9, height: 16, sha256: sha, alt: "Cover", transform: null, designStatus: "approved",
    };
    const written = asset({ version: 2 });
    const swapDb = database((sql) => sql.includes("COALESCE(MAX") ? [{ version: 2 }] : sql.includes("WHERE a.id=$1") ? [written] : []);
    const swapped = await swapMedia(swapDb.tx, "course", input);
    expect(swapDb.sql.some((sql) => sql.includes("RETURNING id"))).toBe(true);
    expect(swapDb.sql.some((sql) => sql.includes("LEFT JOIN media_objects"))).toBe(true);
    expect(swapDb.sql.some((sql) => /RETURNING[\s\S]*\bmo\b/.test(sql))).toBe(false);
    expect(swapDb.locks).toEqual(["media-maintenance:shared", "media-owner:", "xact:media:course:course-1:poster_9x16:default"]);
    expect(swapped.sha256).toBe(sha);
    const rollbackDb = database(() => [asset({ isActive: false, version: 1 })]);
    const restored = await rollbackMedia(rollbackDb.tx, "course", "course-1", "poster_9x16", "default", 1);
    expect(restored).toMatchObject({ id: "asset-1", isActive: true, version: 1 });
    const inactive = database(() => [asset({ isActive: false, variant: "alt" })]);
    const removed = await deleteMedia(inactive.tx, "course", "course-1", "poster_9x16", "alt", 1, { apply: false });
    expect(removed.targets).toHaveLength(1);
    expect(inactive.sql.join("\n")).not.toMatch(/LOCK\s+TABLE/i);
  });
});
