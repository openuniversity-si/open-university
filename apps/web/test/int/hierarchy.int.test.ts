import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { call, createHarness, seedCatalog, seedDraftCourse, type Harness, type Seed } from "../fixtures/admin-catalog.ts";

async function institution(h: Harness, slug: string): Promise<string> {
  return (await h.pool.query<{ id: string }>("INSERT INTO authors (slug, name, monogram, kind) VALUES ($1, $1, 'U', 'institution') RETURNING id", [slug])).rows[0]?.id ?? "";
}

/** Real PostgreSQL commit-time proofs; no external services. */
describe("institution hierarchy (INV-H1/H5/M4)", () => {
  let h: Harness, seed: Seed;
  beforeAll(() => { h = createHarness(); });
  beforeEach(async () => { seed = await seedCatalog(h); });
  afterAll(async () => { await h.close(); });

  it("an insert without kind fails, including the admin API (X4)", async () => {
    await expect(h.pool.query("INSERT INTO authors (slug, name, monogram) VALUES ('missing-kind', 'Missing', 'M')")).rejects.toMatchObject({ code: "23502", column: "kind" });
    expect((await call(h, "POST", "/authors", { body: { slug: "missing-kind", name: "Missing", monogram: "M" } })).status).toBe(400);
  });
  it("D-016: a curated row without an institution, or a second row for the same institution, is refused", async () => {
    await expect(h.pool.query("INSERT INTO home_rows (id, kind, title, position) VALUES ('missing-parent', 'curated', 'Missing', 3)")).rejects.toMatchObject({ code: "23514", constraint: "home_rows_institution" });
    await expect(h.pool.query("INSERT INTO home_rows (id, kind, institution_id, title, position) VALUES ('second-row', 'curated', $1, 'Second', 3)", [seed.institution])).rejects.toMatchObject({ code: "23505", constraint: "home_rows_institution_unique" });
  });
  it("D-017: publishing a course without an area is refused; a draft may have none", async () => {
    await expect(h.pool.query("UPDATE courses SET area_id = NULL WHERE id = $1", [seed.courses.alpha])).rejects.toMatchObject({ code: "23514", constraint: "courses_published_area" });
    const draft = await seedDraftCourse(h, seed, "area-draft");
    await h.pool.query("UPDATE courses SET area_id = NULL WHERE id = $1", [draft.id]);
    await expect(h.pool.query("UPDATE courses SET status = 'published' WHERE id = $1", [draft.id])).rejects.toMatchObject({ code: "23514", constraint: "courses_published_area" });
  });
  it.each(["institution", "row"] as const)("INV-M4: commit fails without the %s's own active cover, despite descendant covers", async (owner) => {
    const client = await h.pool.connect();
    try {
      await client.query("BEGIN");
      await client.query("UPDATE catalog_media SET is_active = false WHERE owner_kind = 'institution' AND owner_id = $1", [owner === "institution" ? seed.institution : "picks"]);
      await expect(client.query("COMMIT")).rejects.toMatchObject({ code: "23514", constraint: "catalog_institution_cover" });
    } finally { await client.query("ROLLBACK"); client.release(); }
  });
  it("INV-H5: commit refuses a curated row grouping courses of another institution", async () => {
    const other = await institution(h, "other-university");
    const client = await h.pool.connect();
    try {
      await client.query("BEGIN");
      await client.query("UPDATE home_rows SET institution_id = $1 WHERE id = 'picks'", [other]);
      await expect(client.query("COMMIT")).rejects.toMatchObject({ code: "23514", constraint: "home_rows_institution_courses" });
    } finally { await client.query("ROLLBACK"); client.release(); }
  });
  it("D-024: a University row or a course points at an institution, never at a lecturer", async () => {
    const draft = await seedDraftCourse(h, seed, "lecturer-draft");
    for (const [statement, id] of [["UPDATE home_rows SET institution_id = $1 WHERE id = $2", "picks"], ["UPDATE courses SET institution_id = $1 WHERE id = $2", draft.id]] as const) {
      const client = await h.pool.connect();
      try {
        await client.query("BEGIN");
        await client.query(statement, [seed.authors[1], id]);
        await expect(client.query("COMMIT")).rejects.toMatchObject({ code: "23514", constraint: "catalog_institution_kind" });
      } finally { await client.query("ROLLBACK"); client.release(); }
    }
  });
  it("D-024: a lecturer may teach at several institutions; the course keeps its lecturer", async () => {
    const other = await institution(h, "second-university");
    const draft = await seedDraftCourse(h, seed, "shared-lecturer");
    await h.pool.query("UPDATE courses SET institution_id = $2 WHERE id = $1", [draft.id, other]);
    expect((await h.pool.query("SELECT author_id, institution_id FROM courses WHERE id IN ($1, $2) ORDER BY institution_id = $3", [seed.courses.alpha, draft.id, other])).rows)
      .toEqual([{ author_id: seed.authors[0], institution_id: seed.institution }, { author_id: seed.authors[0], institution_id: other }]);
  });
  it("INV-M4: cover and row arriving in the same transaction pass even when the cover is last", async () => {
    const draft = await seedDraftCourse(h, seed, "new-institution-course");
    const fresh = await institution(h, "new-institution");
    const client = await h.pool.connect();
    try {
      await client.query("BEGIN");
      await client.query("UPDATE courses SET institution_id = $2, status = 'published' WHERE id = $1", [draft.id, fresh]);
      await client.query("INSERT INTO home_rows (id, kind, institution_id, title, position) VALUES ('new-institution-row', 'curated', $1, 'New institution', 3)", [fresh]);
      await client.query("INSERT INTO home_row_items (row_id, course_id, position) VALUES ('new-institution-row', $1, 1)", [draft.id]);
      for (const [ownerId, kind, id] of [[fresh, "poster_9x16", "new-institution-cover"], ["new-institution-row", "university_cover_9x16", "new-row-cover"]]) {
        await client.query(`INSERT INTO catalog_media (id, owner_kind, owner_id, kind, variant, media_sha256, url, pathname, width, height, sha256, alt, transform, design_status, version)
          SELECT $1, 'institution', $2, $3, variant, media_sha256, url, pathname, width, height, sha256, alt, transform, design_status, 1
          FROM catalog_media WHERE owner_kind = 'institution' AND owner_id = 'picks' AND is_active LIMIT 1`, [id, ownerId, kind]);
      }
      await expect(client.query("COMMIT")).resolves.toMatchObject({ command: "COMMIT" });
    } finally { await client.query("ROLLBACK"); client.release(); }
  });
});
